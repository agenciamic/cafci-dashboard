#!/usr/bin/env python3
"""
Genera docs/index.html con links a los dos dashboards más recientes
y un listado del historial.
"""
import pathlib, datetime, re

docs = pathlib.Path("docs")
docs.mkdir(exist_ok=True)

today = datetime.date.today().strftime("%d/%m/%Y")
now   = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

# Buscar archivos históricos con fecha
def get_dated_files(pattern):
    files = sorted(docs.glob(pattern), reverse=True)
    result = []
    for f in files:
        m = re.search(r"(\d{8})", f.name)
        if m:
            d = m.group(1)
            fecha = f"{d[6:8]}/{d[4:6]}/{d[0:4]}"
            result.append({"file": f.name, "fecha": fecha})
    return result[:20]  # últimos 20

hist_gen    = get_dated_files("CAFCI_Dashboard_*.html")
hist_quiron = get_dated_files("Quiron_PM_Dashboard_*.html")

def hist_rows(items, label):
    if not items:
        return "<p style='color:#888;font-size:12px'>Sin archivos históricos aún.</p>"
    rows = "".join(
        f'<tr><td><a href="{x["file"]}" target="_blank">{x["fecha"]}</a></td></tr>'
        for x in items
    )
    return f"<table style='width:100%;border-collapse:collapse;font-size:12px'><tbody>{rows}</tbody></table>"

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>CAFCI Dashboard — Quiron AM</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f5f5f3; color: #1a1a18; font-size: 14px; line-height: 1.5;
    }}
    .page {{ max-width: 860px; margin: 0 auto; padding: 2rem 1rem 4rem }}
    header {{ margin-bottom: 2rem; border-bottom: 1px solid #d3d1c7; padding-bottom: 1rem }}
    header h1 {{ font-size: 20px; font-weight: 600 }}
    header p {{ font-size: 12px; color: #888780; margin-top: 4px }}
    .logo {{ display: inline-block; background: #1e3a5f; color: #fff;
             font-size: 13px; font-weight: 600; padding: 4px 12px;
             border-radius: 6px; margin-bottom: 12px; letter-spacing: .5px }}
    .cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 2rem }}
    @media(max-width:600px) {{ .cards {{ grid-template-columns: 1fr }} }}
    .card {{
      background: #fff; border: 1px solid #d3d1c7; border-radius: 12px;
      padding: 1.25rem; display: flex; flex-direction: column; gap: 10px;
    }}
    .card h2 {{ font-size: 15px; font-weight: 500 }}
    .card p {{ font-size: 12px; color: #888780 }}
    .btn {{
      display: inline-block; padding: 10px 20px; border-radius: 8px;
      font-size: 13px; font-weight: 500; text-decoration: none;
      text-align: center; margin-top: auto;
    }}
    .btn-primary {{ background: #1e3a5f; color: #fff }}
    .btn-secondary {{ background: #f0efe8; color: #1a1a18; border: 1px solid #d3d1c7 }}
    .btn:hover {{ opacity: .85 }}
    .hist {{ background: #fff; border: 1px solid #d3d1c7; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem }}
    .hist h3 {{ font-size: 13px; font-weight: 500; margin-bottom: 10px; color: #444 }}
    .hist table td {{ padding: 4px 0; border-bottom: 1px solid #f0efe8 }}
    .hist table td a {{ color: #1e3a5f; text-decoration: none }}
    .hist table td a:hover {{ text-decoration: underline }}
    .badge {{ background: #eaf3de; color: #27500a; border-radius: 20px;
              padding: 2px 10px; font-size: 11px; font-weight: 500 }}
    footer {{ text-align: center; font-size: 11px; color: #b4b2a9; margin-top: 2rem }}
  </style>
</head>
<body>
<div class="page">

  <header>
    <div class="logo">QUIRON AM</div>
    <h1>Dashboard de Fondos Comunes de Inversión</h1>
    <p>Actualizado automáticamente todos los días hábiles &nbsp;·&nbsp; Última actualización: {now} ART</p>
  </header>

  <div class="cards">
    <div class="card">
      <h2>📊 Dashboard de Mercado</h2>
      <p>Patrimonio total del mercado, distribución por tipo de fondo y sociedad gerente, y top rendimientos del día.</p>
      <span class="badge" style="width:fit-content">CAFCI · Mercado completo</span>
      <a href="general.html" class="btn btn-primary" target="_blank">Ver Dashboard General →</a>
    </div>
    <div class="card">
      <h2>🎯 Dashboard Quiron AM</h2>
      <p>Vista de Portfolio Manager: rendimiento de los fondos Quiron vs. la mediana del mercado, rankings y percentiles.</p>
      <span class="badge" style="width:fit-content">Quiron AM · Vista interna</span>
      <a href="quiron.html" class="btn btn-primary" target="_blank">Ver Dashboard Quiron →</a>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div class="hist">
      <h3>📁 Historial — Dashboard General</h3>
      {hist_rows(hist_gen, "General")}
    </div>
    <div class="hist">
      <h3>📁 Historial — Dashboard Quiron</h3>
      {hist_rows(hist_quiron, "Quiron")}
    </div>
  </div>

  <footer>
    Datos: Cámara Argentina de Fondos Comunes de Inversión (CAFCI) · 
    Los valores son orientativos y están sujetos a revisión oficial.
  </footer>

</div>
</body>
</html>"""

(docs / "index.html").write_text(html, encoding="utf-8")
print(f"index.html generado en {docs / 'index.html'}")
