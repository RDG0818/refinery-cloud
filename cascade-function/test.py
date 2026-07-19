from cascade_logic import get_adt_client, find_downstream_twins, cascade_failure
import json
client = get_adt_client()
query = f"Select * FROM digitaltwins"
twins = list(client.query_twins(query))

relations = []
for twin in twins:
    twin_id = twin['$dtId']
    for rel in client.list_relationships(twin_id):
        relations.append(rel)
print(relations)