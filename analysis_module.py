"""THIS MODULE WILL BE USED TO ANALYZE THE SYNTHETIC FHIR DATA LOADED INTO THE SERVER. 
IT INCLUDES FUNCTIONS TO QUERY THE FHIR API, EXTRACT INSIGHTS, AND GENERATE REPORTS ON PATIENT DEMOGRAPHICS, 
CLINICAL CONDITIONS, AND TREATMENT PATTERNS. 

NOTE: This still a work in progress, targeting to meet all goals for TP03.   """

# inports
from datetime import date, datetime
import matplotlib.pyplot as plt
# import pprint as prettyPrnt
import seaborn as sns
import pandas as pd
import requests
import json


# class definition
class FHIRDataAnalyzer:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.headers = {"Accept": "application/fhir+json"}
    
    def get_patients(self, count: int = 500) -> list:
        url = f"{self.base_url}/Patient"
        params = {"_count": count}
        response = self.session.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        bundle = response.json()
        return [entry.get("resource", {}) for entry in bundle.get("entry", [])]
        
    # get patient data using patient ID, and return the patient resource as a dictionary
    def get_patient_data(self, patient_id: str) -> dict:
        url = f"{self.base_url}/Patient/{patient_id}"
        response = self.session.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    # get patient age group using patient ID, and return a string representing the age group
    def get_patient_age_group(self, patient_id: str=None, birth_date: date=None) -> str:
        if birth_date is None:
            patient_data = self.get_patient_data(patient_id)
            birth_date = patient_data.get("birthDate")
            if not birth_date:
                return "Unknown"
        else:
            today = datetime.today()
            birth_year = int(birth_date.split("-")[0])
            age = today.year - birth_year
        
        if age < 18:
            return "0-18"
        elif age < 40:
            return "18-39"
        else:
            return "40-64"
    
    # get all covid conditions for a patient using patient ID, and return a list of condition resources as dictionaries
    def get_covid_symptoms_by_patient(self, patient_id: str, symptom_dict: dict) -> list:
        cond_url = f"{self.base_url}/Condition"
        cond_params = {
            "patient": patient_id,
            "_count": 100  
        }
        results = {
            "patient_id": patient_id,
            "symptoms_count": 0
            }
            
            # prettyPrnt.pprint(f"results structure: {results}")
        try:
            cond_response = self.session.get(cond_url, headers=self.headers, params=cond_params)
            cond_response.raise_for_status()
            
            cond_bundle = cond_response.json()
            # prettyPrnt.pprint(f"count: {cond_bundle.get('total', 0)}")
            
            # all conditions for this patient
            cond_entries = cond_bundle.get("entry", [])
            
            for entry in cond_entries:
                resource = entry.get("resource", {})
                
                # Check the codes inside this condition resource
                codings = resource.get("code", {}).get("coding", [])
                for coding in codings:
                    server_code = coding.get("code")
                    
                    for _, target_code in symptom_dict.items():
                        if server_code == target_code:
                            # map result and patient ID to symptom name
                            results["symptoms_count"] += 1
                        else:
                            pass
                        #     print(f"  Code {server_code} does not match target code {target_code} for symptom {symptom_name}")

        except requests.exceptions.RequestException as e:
            # print(f"  Error querying server for patient {patient_id}: {e}")
            pass

        return results
    
    # covid test :)
    def patient_has_covid(self, patient_id: str) -> bool:
        url = f"{self.base_url}/Condition"
        params = {
            "patient": patient_id,
            "code": "840539006"  # SNOMED code for COVID-19
        }
        try:
            response = self.session.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            bundle = response.json()
            return bundle.get("total", 0) > 0
        except requests.exceptions.RequestException as e:
            print(f"  Error checking COVID status for patient {patient_id}: {e}")
            return False
        
        
    ### Visualization functions and other analytics helpers
        
    # covid syptom distribution by age group
    def covid_symptom_distribution_by_age_group(self, viz_data: dict) -> None:
        df_viz = pd.DataFrame(viz_data)

        # Sort age groups so they display chronologically on the chart's X-axis
        age_order = sorted([g for g in df_viz['age_group'].unique() if g != "Unknown"]) + ["Unknown"]
        df_viz['age_group'] = pd.Categorical(df_viz['age_group'], categories=age_order, ordered=True)
        
        plt.figure(figsize=(12, 7))
        sns.set_theme(style="whitegrid")

        sns.boxplot(
            data=df_viz, 
            x="age_group", 
            y="symptom_count", 
            hue="covid_positive",
            palette={"Positive":"#e74c3c", "Negative": "#3498db"}, # Distinct clinical colors
            fliersize=0, # Hide standard outliers to avoid doubling up with stripplot
            boxprops=dict(alpha=0.3) # Make boxes semi-transparent
        )

        # overlay
        sns.stripplot(
            data=df_viz, 
            x="age_group", 
            y="symptom_count", 
            hue="covid_positive",
            palette={"Positive": "#c0392b", "Negative": "#2980b9"},
            dodge=True, # Align dots perfectly with their respective boxplots
            jitter=0.2, # Give dots breathing room to prevent overlap stack
            size=6,
            alpha=0.8
        )

        # Clean up redundant duplicate legends caused by combining plots
        handles, labels = plt.gca().get_legend_handles_labels()
        plt.legend(handles[0:2], labels[0:2], title="COVID-19 Status", loc="upper right", frameon=True)

        # Polish titles and visual text
        plt.title("Symptom Density Distribution Across Patient Age Cohorts", fontsize=16, fontweight="bold", pad=20)
        plt.xlabel("Patient Age Demographics", fontsize=12, labelpad=10)
        plt.ylabel("Active Symptom Counts", fontsize=12, labelpad=10)
        plt.ylim(-0.5, df_viz['symptom_count'].max() + 1) # Set buffer bounds so zero-values don't clip

        plt.tight_layout()
        plt.show()