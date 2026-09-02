import yaml

def load_config(file_path):
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)

def get_api_keys():
    return load_config('config/api_keys.yaml')

def get_db_config():
    return load_config('config/db_config.yaml')
