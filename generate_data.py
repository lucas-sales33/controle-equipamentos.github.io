#!/usr/bin/env python3
"""
Fetches ADO data from all 4 projects and regenerates index.html.
Used by GitHub Actions (runs every hour).

Requires env vars:
  AZURE_DEVOPS_PAT   - Azure DevOps Personal Access Token
  AZURE_DEVOPS_ORG   - https://dev.azure.com/envioequipamentos  (optional, has default)
"""

import os, sys, json, base64, gzip, time
import urllib.request, urllib.error

ORG_URL = os.environ.get("AZURE_DEVOPS_ORG", "https://dev.azure.com/envioequipamentos")
PAT = os.environ.get("AZURE_DEVOPS_PAT", "")

if not PAT:
    print("ERROR: AZURE_DEVOPS_PAT not set", file=sys.stderr)
    sys.exit(1)

AUTH = base64.b64encode(f":{PAT}".encode()).decode()
HEADERS = {"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"}

PROJECTS = [
    {
        "name": "TRACK_EQUIPAMENTOS",
        "id": "a5323e74-0000-0000-0000-000000000000",  # placeholder; WIQL uses name
        "state_field": "Custom.ESTADO",
        "open_state": "A FAZER",
        "fields": ["System.Id","System.Title","System.State","System.AssignedTo",
                   "System.CreatedDate","System.ChangedDate","System.TeamProject",
                   "Custom.COLABORADOR","Custom.UPGRADE","Custom.DATADEINICIO",
                   "Custom.EMAILPESSOAL","Custom.PROJETO","Custom.GESTOR",
                   "Custom.MES","Custom.ENDERECO","Custom.TIPODECONTRATACAO",
                   "Custom.TELEFONE","Custom.SEDE4","Custom.ENDERECOFINALL1",
                   "Custom.FormadeEnvio","Custom.CPF","Custom.LOCALRETIRAEQUIP",
                   "Microsoft.VSTS.Common.Priority"],
    },
    {
        "name": "RETORNO_EQUIPAMENTOS",
        "fields": ["System.Id","System.Title","System.State","System.AssignedTo",
                   "System.CreatedDate","System.ChangedDate","System.TeamProject",
                   "Custom.NOMEDOCOLABORADOR","Custom.EMAILPESSOAL","Custom.GESTOR",
                   "Custom.MES","Custom.ENDERECO","Custom.TELEFONE",
                   "Custom.CENTRODECUSTO","Custom.DESCRICAOCC","Custom.DOCUMENTOS",
                   "Custom.PATRIMONIO","Custom.employee_id",
                   "Microsoft.VSTS.Common.Priority"],
    },
    {
        "name": "CONTROLE DE ENVIO DOS ACESSOS",
        "fields": ["System.Id","System.Title","System.State","System.AssignedTo",
                   "System.CreatedDate","System.ChangedDate","System.TeamProject",
                   "Custom.COLABORADOR","Custom.EMAILPESSOAL","Custom.PROJETO",
                   "Custom.GESTOR","Custom.ENDERECO","Custom.TIPODECONTRATACAO",
                   "Custom.TELEFONE","Custom.DATADOEMAIL1","Custom.DOMINIODOEMAIL",
                   "Custom.CARGO","Custom.DATADEINICIO2","Custom.PreadmissionID",
                   "Microsoft.VSTS.Common.Priority"],
    },
    {
        "name": "ENVIO DE MAQUINAS",
        "fields": ["System.Id","System.Title","System.State","System.AssignedTo",
                   "System.CreatedDate","System.ChangedDate","System.TeamProject",
                   "Custom.COLABORADOR","Custom.UPGRADE","Custom.DATADEINICIO",
                   "Custom.EMAIL","Custom.PROJETO","Custom.GESTOR","Custom.ENDERECO",
                   "Custom.TIPODECONTRATACAO","Custom.TELEFONE","Custom.SEDE4",
                   "Custom.FormadeEnvio","Custom.LOCALRETIRAEQUIP",
                   "Microsoft.VSTS.Common.Priority"],
    },
]


def ado_request(url, body=None, method=None, retries=3):
    data = json.dumps(body).encode() if body else None
    m = method or ("POST" if data else "GET")
    req = urllib.request.Request(url, data=data, method=m)
    for k, v in HEADERS.items():
        req.add_header(k, v)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            print(f"  HTTP {e.code} on attempt {attempt+1}: {body_text[:200]}", file=sys.stderr)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error on attempt {attempt+1}: {e}", file=sys.stderr)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_project_items(project):
    pname = project["name"]
    fields = project["fields"]
    print(f"  Querying {pname}...")

    wiql_url = f"{ORG_URL}/{urllib.parse.quote(pname)}/_apis/wit/wiql?api-version=7.1"
    wiql_body = {"query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{pname}' ORDER BY [System.ChangedDate] DESC"}
    result = ado_request(wiql_url, body=wiql_body)
    ids = [wi["id"] for wi in result.get("workItems", [])]
    print(f"    Found {len(ids)} work items")

    if not ids:
        return []

    items = []
    batch_size = 200
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        batch_url = f"{ORG_URL}/{urllib.parse.quote(pname)}/_apis/wit/workitemsbatch?api-version=7.1"
        batch_body = {"ids": batch, "fields": fields}
        resp = ado_request(batch_url, body=batch_body)
        raw = resp.get("value", [])
        for wi in raw:
            f = wi.get("fields", {})
            assigned = f.get("System.AssignedTo", {})
            if isinstance(assigned, dict):
                assigned_name = assigned.get("displayName", "")
                assigned_email = assigned.get("uniqueName", "")
            else:
                assigned_name = str(assigned) if assigned else ""
                assigned_email = ""
            item = {
                "id": wi["id"],
                "title": f.get("System.Title",""),
                "state": f.get("System.State",""),
                "assignedTo": assigned_name,
                "assignedEmail": assigned_email,
                "createdDate": (f.get("System.CreatedDate","") or "")[:10],
                "changedDate": (f.get("System.ChangedDate","") or "")[:10],
                "project": f.get("System.TeamProject", pname),
                "priority": f.get("Microsoft.VSTS.Common.Priority"),
            }
            # Add custom fields
            for field in fields:
                if field.startswith("Custom."):
                    key = field.split(".")[-1]
                    item[key] = f.get(field, "")
            items.append(item)
        print(f"    Batch {i//batch_size+1}: fetched {len(raw)} items")
        if i + batch_size < len(ids):
            time.sleep(0.3)

    return items


def main():
    import urllib.parse

    db = {}
    for proj in PROJECTS:
        print(f"Fetching {proj['name']}...")
        try:
            items = fetch_project_items(proj)
            db[proj["name"]] = items
            print(f"  OK: {len(items)} items")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            db[proj["name"]] = []

    # Compress and encode
    print("Compressing data...")
    json_bytes = json.dumps(db, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(json_bytes, compresslevel=9)
    b64 = base64.b64encode(compressed).decode()
    print(f"  JSON: {len(json_bytes):,} bytes → Compressed: {len(compressed):,} bytes → B64: {len(b64):,} chars")

    # Read template and inject data
    template_path = os.path.join(os.path.dirname(__file__), "template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    if "__DATA_B64__" not in template:
        print("ERROR: template.html missing __DATA_B64__ placeholder", file=sys.stderr)
        sys.exit(1)

    html = template.replace('"__DATA_B64__"', f'"{b64}"')

    # Write index.html
    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    total_items = sum(len(v) for v in db.values())
    print(f"index.html gerado: {len(html):,} bytes, {total_items:,} work items")


if __name__ == "__main__":
    main()
