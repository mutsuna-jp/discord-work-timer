import sys
try:
    import yaml
except Exception as e:
    print('missing pyyaml:', e)
    sys.exit(1)
try:
    with open('ci.yml','r',encoding='utf-8') as f:
        yaml.safe_load(f)
    print('YAML parsed OK')
except Exception as e:
    print('YAML parse error:', e)
    sys.exit(1)
