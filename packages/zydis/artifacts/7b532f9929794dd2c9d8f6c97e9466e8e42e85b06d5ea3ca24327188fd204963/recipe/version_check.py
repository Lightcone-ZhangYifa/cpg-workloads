import argparse, importlib.metadata, json
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('version');a=p.parse_args()
actual=importlib.metadata.version(a.name)
assert actual==a.version,(a.name,actual,a.version)
print(json.dumps({'status':'passed','distribution':a.name,'expected':a.version,'actual':actual}))
