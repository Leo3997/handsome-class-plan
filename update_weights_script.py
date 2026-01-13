import json
import os

file_path = r'static\rules\shaoxing_rules.json'

def update_weights():
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        
        for rule in data:
            if 'weight' in rule:
                rule['weight'] = 100
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("Success: All weights updated to 100.")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    update_weights()
