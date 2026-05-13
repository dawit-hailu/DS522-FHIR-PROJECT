# import zipfile
# import requests
# import time
# from concurrent.futures import ThreadPoolExecutor
# from typing import List, Tuple

# class FHIRBulkLoader:
#     def __init__(self, base_url: str, max_workers: int = 5):
#         # initialize loader with base URL and max workers for threading
#         self.base_url = base_url.rstrip('/')
#         self.max_workers = max_workers
#         self.session = requests.Session()
#         self.headers = {"Content-Type": "application/fhir+json"}

#     def _upload_resource(self, task: Tuple[str, bytes]) -> str:
#         #Helper method to handle a single POST request
#         file_name, data = task
#         try:
#             # We POST to the base URL assuming these are Transaction/Batch Bundles
#             response = self.session.post(
#                 self.base_url, 
#                 data=data, 
#                 headers=self.headers, 
#                 timeout=30
#             )
#             if response.status_code in [200, 201]:
#                 return f"SUCCESS|{file_name}"
#             return f"FAILED|{file_name}|{response.status_code}|{response.text[:100]}"
#         except Exception as e:
#             return f"ERROR|{file_name}|{str(e)}"

#     def load_from_zip(self, zip_path: str):
#         #Extracts JSON files from a ZIP and uploads them using a thread pool
#         start_time = time.time()
#         tasks = []

#         print(f"Opening {zip_path}...")
#         with zipfile.ZipFile(zip_path, 'r') as z:
#             all_files = [f for f in z.namelist() if f.endswith('.json')]
            
#             json_files = sorted(
#                 all_files, 
#                 key=lambda x: 0 if any(word in x.lower() for word in ['practitioner', 'hospital', 'organization']) else 1
#             )

#             print(f"Found {len(json_files)} resources. Preparing payload (priority sorting applied)...")
            
#             for file_name in json_files:
#                 with z.open(file_name) as f:
#                     tasks.append((file_name, f.read()))

#         print(f"Starting upload to {self.base_url} using {self.max_workers} workers...")
#         with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
#             results = list(executor.map(self._upload_resource, tasks))

#         self._process_results(results, time.time() - start_time)

#     def _process_results(self, results: List[str], duration: float):
#         #Parses the thread results and prints a final summary
#         success_count = sum(1 for r in results if r.startswith("SUCCESS"))
#         failures = [r for r in results if not r.startswith("SUCCESS")]
        
#         print(f"Total Resources Processed: {len(results)}")
#         print(f"Successfully Uploaded:   {success_count}")
#         print(f"Failed/Errors:           {len(failures)}")
        
#         if failures:
#             for f in failures[:5]:
#                 print(f"  - {f}")
import zipfile
import requests
import time
import csv
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

class FHIRBulkLoader:
    def __init__(self, base_url: str, max_workers: int = 5, chunk_size: int = 50):
        self.base_url = base_url.rstrip('/')
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.session = requests.Session()
        self.headers = {"Content-Type": "application/fhir+json"}
        
        self.resource_config = {
            "patients.csv": {"type": "Patient", "map": {"GENDER": "gender", "BIRTHDATE": "birthDate", "FIRST": "name[0].given[0]", "LAST": "name[0].family"}},
            "conditions.csv": {"type": "Condition", "map": {"START": "recordedDate", "PATIENT": "subject.reference", "CODE": "code.coding[0].code", "DESCRIPTION": "code.coding[0].display"}},
            "observations.csv": {"type": "Observation", "map": {"DATE": "effectiveDateTime", "PATIENT": "subject.reference", "CODE": "code.coding[0].code", "VALUE": "valueQuantity.value"}},
            "encounters.csv": {"type": "Encounter", "map": {"START": "period.start", "STOP": "period.end", "PATIENT": "subject.reference", "ENCOUNTERCLASS": "class.code"}},
            "procedures.csv": {"type": "Procedure", "map": {"START": "performedPeriod.start", "PATIENT": "subject.reference", "CODE": "code.coding[0].code"}},
            "medications.csv": {"type": "MedicationRequest", "map": {"START": "authoredOn", "PATIENT": "subject.reference", "CODE": "medicationCodeableConcept.coding[0].code"}}
        }

    def _normalize_value(self, path: str, value: str) -> str:
        if path == "gender":
            mapping = {"M": "male", "F": "female", "MALE": "male", "FEMALE": "female"}
            return mapping.get(value.upper(), "other")
        if ".reference" in path and not (value.startswith("Patient/") or value.startswith("Organization/")):
            # Synthea clinical files usually refer to Patients
            return f"Patient/{value}"
        return value

    def _set_nested(self, obj: dict, path: str, value: str):
        parts = path.split('.')
        for i, part in enumerate(parts[:-1]):
            if '[' in part:
                name, idx = part.replace(']', '').split('[')
                obj = obj.setdefault(name, [])
                while len(obj) <= int(idx): obj.append({})
                obj = obj[int(idx)]
            else:
                obj = obj.setdefault(part, {})
        last = parts[-1]
        if '[' in last:
            name, idx = last.replace(']', '').split('[')
            obj.setdefault(name, []).insert(int(idx), value)
        else:
            obj[last] = value

    def _create_bundles(self, filename: str, content: bytes) -> List[bytes]:
        config = self.resource_config.get(filename.lower())
        if not config: return []
        reader = csv.DictReader(io.StringIO(content.decode('utf-8')))
        all_entries = []
        for row in reader:
            res_id = row.get('Id') or row.get('id') or str(uuid.uuid4())
            resource = {"resourceType": config["type"], "id": res_id}
            for csv_col, fhir_path in config["map"].items():
                val = row.get(csv_col)
                if val:
                    val = self._normalize_value(fhir_path, val)
                    self._set_nested(resource, fhir_path, val)
            
            # Use PUT (update) instead of POST to ensure ID consistency and prevent duplicates
            all_entries.append({
                "fullUrl": f"{config['type']}/{res_id}",
                "resource": resource,
                "request": {"method": "PUT", "url": f"{config['type']}/{res_id}"}
            })
        
        chunks = [all_entries[i:i + self.chunk_size] for i in range(0, len(all_entries), self.chunk_size)]
        return [json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": c}).encode('utf-8') for c in chunks]

    def _upload_batch(self, tasks: List[Tuple[str, bytes]]):
        if not tasks: return
        print(f"Starting upload of {len(tasks)} bundles...")
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(self._upload_task, tasks))
        
        success = sum(1 for r in results if r.startswith("SUCCESS"))
        print(f"Batch complete: {success}/{len(results)} successful.")

    def _upload_task(self, task: Tuple[str, bytes]) -> str:
        name, data = task
        try:
            res = self.session.post(self.base_url, data=data, headers=self.headers, timeout=60)
            if res.status_code in [200, 201]: return f"SUCCESS|{name}"
            return f"FAILED|{name}|{res.status_code}|{res.text[:150]}"
        except Exception as e:
            return f"ERROR|{name}|{str(e)}"

    def load_from_zip(self, zip_path: str, file_type: str = 'json'):
        start_time = time.time()
        phase1_tasks = [] # Patients
        phase2_tasks = [] # Clinical Data

        with zipfile.ZipFile(zip_path, 'r') as z:
            for f_name in z.namelist():
                fname_lower = f_name.lower()
                if file_type == 'csv' and fname_lower in self.resource_config:
                    with z.open(f_name) as f:
                        bundles = self._create_bundles(f_name, f.read())
                        task_list = phase1_tasks if fname_lower == "patients.csv" else phase2_tasks
                        for i, b in enumerate(bundles):
                            task_list.append((f"{f_name}_part_{i}", b))
                elif file_type == 'json' and f_name.endswith('.json'):
                    with z.open(f_name) as f:
                        phase2_tasks.append((f_name, f.read()))

        print("--- PHASE 1: Loading Patients ---")
        self._upload_batch(phase1_tasks)
        
        print("\n--- PHASE 2: Loading Clinical Records ---")
        self._upload_batch(phase2_tasks)
        
        print(f"\nTotal time: {time.time()-start_time:.2f}s")