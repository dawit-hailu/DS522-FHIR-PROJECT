import zipfile
import requests
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

class FHIRBulkLoader:
    def __init__(self, base_url: str, max_workers: int = 5):
        # initialize loader with base URL and max workers for threading
        self.base_url = base_url.rstrip('/')
        self.max_workers = max_workers
        self.session = requests.Session()
        self.headers = {"Content-Type": "application/fhir+json"}

    def _upload_resource(self, task: Tuple[str, bytes]) -> str:
        #Helper method to handle a single POST request
        file_name, data = task
        try:
            # We POST to the base URL assuming these are Transaction/Batch Bundles
            response = self.session.post(
                self.base_url, 
                data=data, 
                headers=self.headers, 
                timeout=30
            )
            if response.status_code in [200, 201]:
                return f"SUCCESS|{file_name}"
            return f"FAILED|{file_name}|{response.status_code}|{response.text[:100]}"
        except Exception as e:
            return f"ERROR|{file_name}|{str(e)}"

    def load_from_zip(self, zip_path: str):
        #Extracts JSON files from a ZIP and uploads them using a thread pool
        start_time = time.time()
        tasks = []

        print(f"Opening {zip_path}...")
        with zipfile.ZipFile(zip_path, 'r') as z:
            all_files = [f for f in z.namelist() if f.endswith('.json')]
            
            json_files = sorted(
                all_files, 
                key=lambda x: 0 if any(word in x.lower() for word in ['practitioner', 'hospital', 'organization']) else 1
            )

            print(f"Found {len(json_files)} resources. Preparing payload (priority sorting applied)...")
            
            for file_name in json_files:
                with z.open(file_name) as f:
                    tasks.append((file_name, f.read()))

        print(f"Starting upload to {self.base_url} using {self.max_workers} workers...")
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(self._upload_resource, tasks))

        self._process_results(results, time.time() - start_time)

    def _process_results(self, results: List[str], duration: float):
        #Parses the thread results and prints a final summary
        success_count = sum(1 for r in results if r.startswith("SUCCESS"))
        failures = [r for r in results if not r.startswith("SUCCESS")]
        
        print(f"Total Resources Processed: {len(results)}")
        print(f"Successfully Uploaded:   {success_count}")
        print(f"Failed/Errors:           {len(failures)}")
        
        if failures:
            for f in failures[:5]:
                print(f"  - {f}")