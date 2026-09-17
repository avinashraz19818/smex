import json

with open('config.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

t_clients = [f'CLIENT_{i}_SESSION' for i in range(1, 7)]
d['telegram_clients'] = t_clients

for o_id, o_cfg in d['owners'].items():
    if 'clients' in o_cfg:
        o_cfg['wingo_accounts'] = o_cfg.pop('clients', [])
        for w in o_cfg['wingo_accounts']:
            w.pop('session_env', None)

with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=4)

print("Updated config.json")
