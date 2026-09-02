from config_loader import get_api_keys, get_db_config

# Test API keys
api_keys = get_api_keys()
print("✅ API keys loaded successfully!\n")
for key, value in api_keys.items():
    print(f"{key}: {value[:6]}...{value[-4:]}")

# Test DB config
print("\n✅ Database config loaded successfully!")
db_conf = get_db_config()

for db, conf in db_conf.items():
    # handle databases that use 'uri' instead of 'host'/'port'
    host = conf.get("host", conf.get("uri", "N/A"))
    port = conf.get("port", "N/A")
    print(f"{db.upper()} → host={host}, port={port}")
