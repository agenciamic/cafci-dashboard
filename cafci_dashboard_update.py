#!/usr/bin/env python3
"""
CAFCI Dashboard Updater
-----------------------
Descarga la planilla diaria de CAFCI, procesa los datos y genera
dos dashboards HTML:
  1. Dashboard general (patrimonio + rendimientos por tipo)
  2. Dashboard Quiron AM (PM view con benchmarks de mediana)

Cómo programarlo para que corra todos los días a las 21hs:
  - Mac / Linux: crontab -e  →  0 21 * * 1-5 python3 /ruta/cafci_dashboard_update.py
  - Windows: Task Scheduler  →  ver README al final de este archivo
"""

import sys, os, re, json, datetime, pathlib
import urllib.request, urllib.error
import numpy as np

# ── dependencias: pip install openpyxl pandas numpy ──────────────────────────
try:
    import pandas as pd
    import openpyxl
except ImportError:
    print("Faltan dependencias. Ejecutá:  pip install pandas openpyxl numpy")
    sys.exit(1)

# ── configuración ─────────────────────────────────────────────────────────────
DOWNLOAD_URL   = "https://api.pub.cafci.org.ar/pb_get"
OUTPUT_DIR     = pathlib.Path(__file__).parent / "dashboards"
SOC_GERENTE    = "Quiron"          # filtro para el dashboard PM
MIN_AUM_BENCH  = 0                 # mediana: no filtra por AUM mínimo
OUTLIER_LIMIT  = 200               # % máximo para benchmarks (excluye reestructuraciones)
# Tipo de cambio fallback — se usa si la API falla. Actualizar de vez en cuando.
FX_MEP_FALLBACK = 1400             # ARS por USD/USB

# ─────────────────────────────────────────────────────────────────────────────
def log(msg): print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

def download_xlsx(url, dest):
    import time
    INTENTOS = 5
    ESPERA   = 30  # segundos entre reintentos
    for intento in range(1, INTENTOS + 1):
        try:
            log(f"Descargando planilla (intento {intento}/{INTENTOS})...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
            log(f"Descarga exitosa → {dest}")
            return True
        except Exception as e:
            log(f"Intento {intento} fallido: {e}")
            if intento < INTENTOS:
                log(f"Reintentando en {ESPERA} segundos...")
                time.sleep(ESPERA)
    log(f"No se pudo descargar después de {INTENTOS} intentos. La web de CAFCI puede estar caída.")
    return False

def assign_tipo(df_raw):
    tipo_map = {}; current = "Otros"
    for i, row in df_raw.iterrows():
        if pd.isna(row.iloc[1]) and pd.notna(row.iloc[0]) and isinstance(row.iloc[0], str):
            s = row.iloc[0]
            if   "Renta Variable"   in s: current = "Renta Variable"
            elif "Renta Fija"       in s: current = "Renta Fija"
            elif "Renta Mixta"      in s: current = "Renta Mixta"
            elif "Mercado de Dinero"in s: current = "Mercado de Dinero"
            elif "PyMes"            in s: current = "PyMEs"
            elif "Infraestructura"  in s: current = "Infraestructura"
            elif "Retorno Total"    in s: current = "Retorno Total"
            elif "ASG"              in s: current = "ASG"
            elif "RG900"            in s: current = "RG900"
            else: current = "Otros"
        tipo_map[i] = current
    return tipo_map

def get_mep(fallback):
    """Obtiene el dólar MEP (bolsa) desde DolarApi.com. Gratis, sin API key.
    Retorna (valor, fuente) donde fuente es 'DolarApi.com' o 'valor manual'."""
    try:
        import urllib.request, json
        url = "https://dolarapi.com/v1/dolares/bolsa"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            mep = round(float(data["venta"]))
            log(f"MEP obtenido de DolarApi.com: ${mep:,}")
            return mep, "DolarApi.com"
    except Exception as e:
        log(f"No se pudo obtener MEP de la API (usando valor manual ${fallback:,}): {e}")
        return fallback, "valor manual"

def load_data(xlsx_path, FX_MEP=None):
    if FX_MEP is None: FX_MEP = FX_MEP_FALLBACK
    log("Procesando Excel...")
    df_raw = pd.read_excel(xlsx_path, skiprows=9, header=0)
    tipo_map = assign_tipo(df_raw)

    COLS = ["Fondo","Moneda","Region","Horizonte","Fecha","Valor_Actual","Valor_Ant",
            "Variac_Pct","Reexp","Var_Mar","Var_Dic","Var_Anual","Cuotap_Actual",
            "Cuotap_Ant","Patrimonio_Actual","Patrimonio_Ant","Market_Share",
            "Soc_Depositaria","Cod_CNV","Calificacion","Cod_CAFCI","Cod_SocGte",
            "Cod_SocDep","Soc_Gerente"]
    df = df_raw.iloc[:, :len(COLS)].copy()
    df.columns = COLS
    df["Tipo"] = df.index.map(tipo_map)
    df = df[df["Fecha"].notna() & (df["Fecha"] != "Unnamed: 4_level_1") & df["Moneda"].notna()]

    for c in ["Patrimonio_Actual","Patrimonio_Ant","Variac_Pct","Var_Mar","Var_Dic","Var_Anual"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["Fondo_Base"] = df["Fondo"].str.replace(r"\s*-\s*Clase\s+.*$", "", regex=True).str.strip()
    df["is_target"]  = df["Soc_Gerente"].str.contains(SOC_GERENTE, case=False, na=False)
    # Convertir fondos en USD y USD Billete (USB) a ARS equivalentes para comparaciones cross-moneda
    fx = df["Moneda"].isin(["USD", "USB"])
    df["Patrimonio_ARS"]     = df["Patrimonio_Actual"].where(~fx, df["Patrimonio_Actual"] * FX_MEP)
    df["Patrimonio_Ant_ARS"] = df["Patrimonio_Ant"].where(~fx, df["Patrimonio_Ant"] * FX_MEP)
    return df

def wavg(g, v, w):
    mask = g[v].notna() & g[w].notna() & (g[w] > 0)
    if mask.sum() == 0: return np.nan
    return (g.loc[mask, v] * g.loc[mask, w]).sum() / g.loc[mask, w].sum()

def aggregate(df):
    agg = df.groupby(["Fondo_Base","Tipo","Moneda"]).apply(lambda g: pd.Series({
        "Patrimonio":     g["Patrimonio_ARS"].sum(),      # siempre en ARS equivalentes
        "Patrimonio_Ant": g["Patrimonio_Ant_ARS"].sum(),  # siempre en ARS equivalentes
        "Patrimonio_orig": g["Patrimonio_Actual"].sum(),  # en moneda original (para display)
        "is_target":      g["is_target"].any(),
        "Soc_Gerente":    g["Soc_Gerente"].dropna().iloc[0] if g["Soc_Gerente"].notna().any() else "",
        "Var_Dia":  wavg(g, "Variac_Pct",  "Patrimonio_Actual"),
        "Var_Mes":  wavg(g, "Var_Mar",     "Patrimonio_Actual"),
        "Var_Anio": wavg(g, "Var_Dic",     "Patrimonio_Actual"),
        "Var_12M":  wavg(g, "Var_Anual",   "Patrimonio_Actual"),
    })).reset_index()

    for m in ["Var_Dia","Var_Mes","Var_Anio","Var_12M"]:
        agg[m+"_c"] = agg[m].where(agg[m].abs() < OUTLIER_LIMIT)

    # mediana por tipo+moneda
    bench = agg.groupby(["Tipo","Moneda"]).apply(lambda g: pd.Series({
        "med_dia":  g["Var_Dia_c"].median(),
        "med_mes":  g["Var_Mes_c"].median(),
        "med_anio": g["Var_Anio_c"].median(),
        "med_12m":  g["Var_12M_c"].median(),
        "n":        len(g),
    })).reset_index()

    # ranking absoluto (1 = mejor) y total de pares activos por grupo
    # solo fondos con patrimonio > 0 y valor no nulo
    for m in ["Var_Dia","Var_Mes","Var_Anio","Var_12M"]:
        # rank descendente: 1 = mayor rendimiento
        agg[f"rank_{m}"] = agg.groupby(["Tipo","Moneda"])[m].rank(
            method="min", ascending=False, na_option="keep"
        )
        # total de fondos activos con valor no nulo en ese grupo
        n_activos = (
            agg[agg["Patrimonio"] > 0]
            .groupby(["Tipo","Moneda"])[m]
            .transform("count")
        )
        agg[f"n_{m}"] = n_activos

        # percentil clásico: % de fondos activos con rendimiento ESTRICTAMENTE menor
        def pct_clasico(g, col):
            activos = g[g["Patrimonio"] > 0][col].dropna()
            n = len(activos)
            if n == 0:
                return pd.Series(np.nan, index=g.index)
            return g[col].apply(
                lambda v: round((activos < v).sum() / n * 100) if pd.notna(v) else np.nan
            )

        agg[f"pct_{m}"] = agg.groupby(["Tipo","Moneda"], group_keys=False).apply(
            lambda g: pct_clasico(g, m)
        )

    return agg, bench

# ─────────────────────────────────────────────────────────────────────────────
# HTML HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def fmt_ars(v):
    if v >= 1e12: return f"${v/1e12:.2f}B"
    if v >= 1e9:  return f"${v/1e9:.1f}M"
    return f"${v/1e6:.0f}K"

def js_arr(items, key=None):
    """Convierte lista de dicts o lista de valores a JSON para JS."""
    return json.dumps(items if key is None else [x[key] for x in items],
                      ensure_ascii=False, default=str)

# ─────────────────────────────────────────────────────────────────────────────
# GENERAL DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def build_general_dashboard(agg, bench, fecha_str, fx_mep=1400, fx_source="fallback"):
    total = agg["Patrimonio"].sum()

    # top 15
    t15 = agg.nlargest(15, "Patrimonio")[["Fondo_Base","Patrimonio","Tipo"]].copy()
    t15["pct"] = (t15["Patrimonio"]/total*100).round(2)

    # por tipo
    pt = agg.groupby("Tipo")["Patrimonio"].sum().reset_index().sort_values("Patrimonio", ascending=False)
    pt["pct"] = (pt["Patrimonio"]/total*100).round(2)

    # por gerente top 15
    pg = agg.groupby("Soc_Gerente")["Patrimonio"].sum().reset_index().sort_values("Patrimonio", ascending=False).head(15)
    pg["pct"] = (pg["Patrimonio"]/total*100).round(2)
    pg["Soc_short"] = pg["Soc_Gerente"].str.replace(r"S\.A\.(U\.)?\s*(S\.G\.F\.C\.I\..*)?$","",regex=True).str.strip()

    # top 5 rendimientos por tipo
    rend_data = {}
    tipos = [t for t in agg["Tipo"].unique() if t != "Otros"]
    for tipo in tipos:
        sub = agg[(agg["Tipo"]==tipo) & (agg["Patrimonio"]>1e9)].copy()
        rend_data[tipo] = {}
        for p, col in [("dia","Var_Dia"),("mes","Var_Mes"),("anio","Var_Anio"),("doce","Var_12M")]:
            s = sub[sub[col+"_c"].notna()].nlargest(15, col)
            rend_data[tipo][p] = [{"n": r["Fondo_Base"][:40], "v": round(float(r[col]),3)}
                                   for _, r in s.iterrows()]

    TIPO_COLORS = ["#3266ad","#5c9bd1","#73726c","#e8a838","#639922","#d85a30","#7f77dd","#b4b2a9","#d4537e","#1d9e75"]

    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CAFCI Dashboard — {fecha_str}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f3;color:#1a1a18;font-size:13px;line-height:1.5}}
.page{{max-width:900px;margin:0 auto;padding:1.25rem 1rem 3rem}}
header{{margin-bottom:1.25rem;border-bottom:1px solid #d3d1c7;padding-bottom:.875rem}}
header h1{{font-size:17px;font-weight:500}}
header p{{font-size:11px;color:#888780;margin-top:3px}}
.card{{background:#fff;border:1px solid #d3d1c7;border-radius:10px;padding:1rem;margin-bottom:1rem}}
.ct{{font-size:13px;font-weight:500;margin-bottom:.875rem}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:1rem}}
.m{{background:#f5f5f3;border-radius:7px;padding:.75rem}}
.ml{{font-size:10px;color:#888780;margin-bottom:3px}}
.mv{{font-size:18px;font-weight:500}}
.ms{{font-size:10px;color:#b4b2a9;margin-top:1px}}
.tabs{{display:flex;gap:2px;border-bottom:1px solid #d3d1c7;margin-bottom:1rem}}
.tab{{padding:5px 13px;font-size:11px;cursor:pointer;border:none;background:none;color:#888780;border-bottom:2px solid transparent;margin-bottom:-1px}}
.tab.on{{color:#1a1a18;border-bottom-color:#1a1a18;font-weight:500}}
.panel{{display:none}}.panel.on{{display:block}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:.875rem}}
.chip{{padding:5px 12px;font-size:11px;border:1px solid #b4b2a9;border-radius:20px;background:none;color:#888780;cursor:pointer}}
.chip.on{{background:#1a1a18;color:#fff;border-color:#1a1a18}}
.pbtns{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:1rem}}
.pbtn{{padding:4px 11px;font-size:11px;border:1px solid #d3d1c7;border-radius:6px;background:none;color:#888780;cursor:pointer}}
.pbtn.on{{background:#3266ad;color:#fff;border-color:#3266ad}}
.warn{{background:#faeeda;color:#854f0b;border-radius:7px;padding:6px 10px;font-size:11px;margin-bottom:10px;display:none}}
.rl{{font-size:13px;font-weight:500;margin-bottom:2px}}
.rs{{font-size:11px;color:#888780;margin-bottom:12px}}
.note{{font-size:10px;color:#b4b2a9;margin-top:8px}}
canvas{{display:block;width:100%}}
footer{{text-align:center;font-size:10px;color:#b4b2a9;margin-top:1.5rem}}
@media(max-width:600px){{.metrics{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<div class="page">
<header>
  <h1>CAFCI — Planilla Diaria de Fondos Comunes de Inversión</h1>
  <p>{fecha_str} &nbsp;·&nbsp; Fuente: Cámara Argentina de FCI &nbsp;·&nbsp; Valores sujetos a revisión</p>
</header>

<div class="card">
  <div class="ct">Patrimonio del mercado</div>
  <div class="tabs">
    <button class="tab on" onclick="pt('p-top15',this)">Top 15 fondos</button>
    <button class="tab" onclick="pt('p-tipo',this)">Por tipo</button>
    <button class="tab" onclick="pt('p-ger',this)">Por soc. gerente</button>
  </div>
  <div id="p-top15" class="panel on">
    <div class="metrics">
      <div class="m"><div class="ml">Patrimonio total</div><div class="mv">{fmt_ars(total)}</div><div class="ms">ARS</div></div>
      <div class="m"><div class="ml">Fondos únicos</div><div class="mv">{len(agg):,}</div><div class="ms">sin contar clases</div></div>
      <div class="m"><div class="ml">Top 15 concentran</div><div class="mv">{t15['pct'].sum():.1f}%</div><div class="ms">del total</div></div>
    </div>
    <canvas id="c-top15"></canvas>
  </div>
  <div id="p-tipo" class="panel">
    <canvas id="c-tipo"></canvas>
  </div>
  <div id="p-ger" class="panel">
    <canvas id="c-ger"></canvas>
  </div>
</div>

<div class="card">
  <div class="ct">Rendimientos — Top 15 por clase de fondo</div>
  <div class="chips" id="tipo-chips"></div>
  <div class="pbtns">
    <button class="pbtn" onclick="sp('dia')">Hoy</button>
    <button class="pbtn on" onclick="sp('mes')">Mes (vs 31/3)</button>
    <button class="pbtn" onclick="sp('anio')">Año (vs dic)</button>
    <button class="pbtn" onclick="sp('doce')">12 meses</button>
  </div>
  <div id="warn" class="warn"></div>
  <div class="rl" id="rl"></div>
  <div class="rs" id="rs"></div>
  <div id="rendWrap" style="position:relative;width:100%;height:240px"><canvas id="c-rend"></canvas></div>
  <div class="note">Rendimiento ponderado por patrimonio. Fondos con AUM &gt; $1.000M.</div>
</div>

<footer>Generado automáticamente · CAFCI · {fecha_str} · Tipo de cambio MEP utilizado: ${fx_mep:,} ARS/USD (fuente: {fx_source})</footer>
</div>

<script>
const DPR=window.devicePixelRatio||1;
function sc(id,h){{const c=document.getElementById(id);const w=c.parentElement.clientWidth-2;
c.style.width=w+'px';c.style.height=h+'px';c.width=w*DPR;c.height=h*DPR;
const ctx=c.getContext('2d');ctx.scale(DPR,DPR);return{{ctx,w,h}};}}
function fmt(v){{if(v>=1e12)return'$'+(v/1e12).toFixed(2)+'B';if(v>=1e9)return'$'+(v/1e9).toFixed(1)+'M';return'$'+(v/1e6).toFixed(0)+'K';}}
function rr(ctx,x,y,w,h,r){{ctx.beginPath();ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);
ctx.quadraticCurveTo(x+w,y,x+w,y+r);ctx.lineTo(x+w,y+h-r);ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
ctx.lineTo(x+r,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-r);ctx.lineTo(x,y+r);ctx.quadraticCurveTo(x,y,x+r,y);ctx.closePath();}}
function hbar(id,labels,values,colors,xLbl){{
const rows=labels.length;const rH=36;const pL=160,pR=20,pT=16,pB=28;
const H=rows*rH+pT+pB;const{{ctx,w}}=sc(id,H);const cW=w-pL-pR;
const maxV=Math.max(...values.map(Math.abs))*1.15||1;
const hasNeg=values.some(v=>v<0);const zero=hasNeg?pL+cW*(Math.abs(Math.min(...values))/maxV*0.5):pL;
ctx.strokeStyle='#d3d1c7';ctx.lineWidth=0.5;ctx.beginPath();ctx.moveTo(zero,pT);ctx.lineTo(zero,pT+rows*rH);ctx.stroke();
ctx.fillStyle='#b4b2a9';ctx.font='10px -apple-system,sans-serif';ctx.textAlign='center';
for(let i=0;i<=4;i++){{const x=pL+(cW*i/4);const val=(maxV*(i/4)*(hasNeg?2:1))-(hasNeg?maxV:0);
ctx.fillText(val.toFixed(val<1&&val>-1?2:1)+'%',x,pT+rows*rH+14);}}
ctx.fillStyle='#888780';ctx.font='10px -apple-system,sans-serif';ctx.textAlign='center';
ctx.fillText(xLbl,pL+cW/2,H-4);
labels.forEach((lbl,i)=>{{const y=pT+i*rH;const bh=rH*0.55;const by=y+(rH-bh)/2;
const v=values[i];const bw=Math.abs(v)/maxV*cW*(hasNeg?0.5:1);const bx=v>=0?zero:zero-bw;
ctx.fillStyle=colors[i]||'#3266ad';rr(ctx,bx,by,Math.max(bw,2),bh,3);ctx.fill();
ctx.fillStyle='#1a1a18';ctx.font='11px -apple-system,sans-serif';
ctx.textAlign=v>=0?'left':'right';ctx.fillText(typeof v==='number'&&v>=1e9?fmt(v):v.toFixed(2)+'%',v>=0?zero+bw+4:zero-bw-4,by+bh*0.68);
ctx.fillStyle='#1a1a18';ctx.font='11px -apple-system,sans-serif';ctx.textAlign='right';
ctx.fillText((lbl.length>22?lbl.slice(0,21)+'…':lbl),pL-8,by+bh*0.68);}});}}

const TOP15L={js_arr([x['Fondo_Base'] for _,x in t15.iterrows()])};
const TOP15V={js_arr([float(x['Patrimonio']) for _,x in t15.iterrows()])};
const TIPOL={js_arr(list(pt['Tipo']))};
const TIPOV={js_arr([float(x) for x in pt['Patrimonio']])};
const TIPOC={json.dumps(TIPO_COLORS[:len(pt)])};
const GERL={js_arr(list(pg['Soc_short']))};
const GERV={js_arr([float(x) for x in pg['Patrimonio']])};
const TIPOS={js_arr(list(rend_data.keys()))};
const REND={json.dumps(rend_data, ensure_ascii=False)};
const PNAMES={{dia:'hoy',mes:'en el mes',anio:'en el año',doce:'en 12 meses'}};
const PLABELS={{dia:'Var. del día (%)',mes:'Var. vs 31/mar (%)',anio:"Var. vs dic'25 (%)",doce:"Var. vs mar'25 (%)"}};

let cTipo=TIPOS[0],cPer='mes',rendChart=null;

function pt(id,btn){{['p-top15','p-tipo','p-ger'].forEach(p=>document.getElementById(p).classList.toggle('on',p===id));
btn.parentElement.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));btn.classList.add('on');drawPat();}}

function drawPat(){{
if(document.getElementById('p-top15').classList.contains('on'))hbar('c-top15',TOP15L,TOP15V,TOP15V.map(()=>'#3266ad'),'Patrimonio');
if(document.getElementById('p-tipo').classList.contains('on'))hbar('c-tipo',TIPOL,TIPOV,TIPOC,'Patrimonio');
if(document.getElementById('p-ger').classList.contains('on'))hbar('c-ger',GERL,GERV,GERV.map(()=>'#3266ad'),'Patrimonio');}}

function buildChips(){{document.getElementById('tipo-chips').innerHTML=TIPOS.map((t,i)=>`<button class="chip${{i===0?' on':''}}" onclick="sTipo('${{t}}',this)">${{t}}</button>`).join('');}}

function sTipo(t,btn){{cTipo=t;document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));btn.classList.add('on');drawRend();}}
function sp(p){{cPer=p;document.querySelectorAll('.pbtn').forEach(b=>b.classList.toggle('on',b.textContent.toLowerCase().includes({{dia:'hoy',mes:'mes',anio:'año',doce:'12'}}[p])));drawRend();}}

function drawRend(){{
const d=REND[cTipo]||{{}};const items=[...(d[cPer]||[])];
const warn=document.getElementById('warn');warn.style.display='none';
document.getElementById('rl').textContent=`Top 15 — ${{cTipo}}`;
document.getElementById('rs').textContent=`Mejores rendimientos ${{PNAMES[cPer]}}`;
const display=[...items].sort((a,b)=>b.v-a.v);
const wrap=document.getElementById('rendWrap');wrap.style.height=(display.length*40+70)+'px';
const cv=document.getElementById('c-rend');cv.style.height=wrap.style.height;
hbar('c-rend',display.map(x=>x.n),display.map(x=>x.v),display.map(x=>x.v>=0?'#3266ad':'#d85a30'),PLABELS[cPer]);}}

window.addEventListener('DOMContentLoaded',()=>{{drawPat();buildChips();drawRend();}});
window.addEventListener('resize',()=>{{drawPat();drawRend();}});
</script></body></html>"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# CONCLUSIONS GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def build_conclusions(funds_js, total_hoy, total_ant, delta_pct):
    """Genera bullets de alertas y oportunidades a partir de los datos del día."""
    bullets = []  # cada item: (tipo, texto)  tipo: alert | warn | opp

    # ── concentración de AUM ────────────────────────────────────────────────
    sorted_f = sorted(funds_js, key=lambda x: x["aum"], reverse=True)
    top1 = sorted_f[0]
    top1_pct = top1["aum"] / (total_hoy / 1e6) * 100
    if top1_pct > 40:
        bullets.append(("alert",
            f"<b>Concentración de AUM:</b> {top1['n']} representa el {top1_pct:.0f}% del patrimonio total "
            f"({fmt_ars(top1['aum']*1e6)}). Un rescate significativo en este fondo tendría impacto directo "
            f"en los ingresos de la firma. Monitorear flujos diariamente."))

    # ── caída de AUM diaria ──────────────────────────────────────────────────
    if delta_pct < -3:
        bullets.append(("alert",
            f"<b>Caída de AUM significativa:</b> el patrimonio total bajó {delta_pct:.1f}% en el día "
            f"({fmt_ars(abs(total_hoy - total_ant))} de salidas netas estimadas). "
            f"Revisar si se trata de rescates o de movimiento de cuotaparte."))
    elif delta_pct < -1:
        bullets.append(("warn",
            f"<b>Leve caída de AUM:</b> {delta_pct:.1f}% respecto al día anterior. "
            f"Monitorear si la tendencia se repite mañana."))

    # ── fondos con rendimiento en rojo (año) ─────────────────────────────────
    underperformers = [f for f in funds_js if f.get("anio") is not None and f["anio"] < 0]
    for f in underperformers:
        pct = f.get("pct_anio")
        pct_txt = f"pctil {pct}° de su categoría" if pct is not None else "por debajo del mercado"
        bullets.append(("alert",
            f"<b>{f['n']} en terreno negativo:</b> acumula {f['anio']:+.2f}% en el año "
            f"({pct_txt}). Evaluar si la estrategia justifica mantenerlo o si conviene "
            f"una revisión del posicionamiento."))

    # ── fondos muy rezagados vs mediana (año) ────────────────────────────────
    laggards = [f for f in funds_js
                if f.get("anio") is not None and f.get("b_anio") is not None
                and f.get("pct_anio") is not None and f["pct_anio"] < 15
                and f["anio"] >= 0]  # ya cubiertos los negativos arriba
    for f in laggards:
        diff = f["anio"] - f["b_anio"]
        bullets.append(("warn",
            f"<b>{f['n']} muy por debajo de la mediana:</b> rinde {f['anio']:+.2f}% en el año "
            f"vs mediana de categoría {f['b_anio']:+.2f}% (diferencia {diff:+.2f}pp, pctil {f['pct_anio']}°). "
            f"Posible punto de fricción con inversores institucionales que comparen contra benchmark."))

    # ── oportunidades de venta: alto rendimiento + bajo AUM ─────────────────
    for f in funds_js:
        if (f.get("pct_anio") is not None and f["pct_anio"] >= 80
                and f.get("aum_rank") is not None and f.get("aum_n") is not None
                and f["aum_rank"] / f["aum_n"] > 0.6):  # top rendimiento pero mitad baja en AUM
            bullets.append(("opp",
                f"<b>Oportunidad comercial — {f['n']}:</b> rendimiento en el año en el pctil "
                f"{f['pct_anio']}° de su categoría pero ocupa el puesto "
                f"{f['aum_rank']}°/{f['aum_n']} por AUM. El track record justifica "
                f"una campaña activa de captación."))

    # ── fondo con buen rendimiento en mes pero rezagado en año ───────────────
    for f in funds_js:
        if (f.get("pct_mes") is not None and f["pct_mes"] >= 85
                and f.get("pct_anio") is not None and f["pct_anio"] < 30):
            bullets.append(("opp",
                f"<b>Recuperación en curso — {f['n']}:</b> pctil {f['pct_mes']}° en el mes "
                f"pero pctil {f['pct_anio']}° en el año. Si la tendencia reciente se sostiene, "
                f"hay una historia de recuperación que comunicar a inversores actuales "
                f"antes de que rescaten."))

    # ── fondo USD con buen rendimiento relativo ───────────────────────────────
    usd_funds = [f for f in funds_js if f["mon"] == "USD" and f.get("pct_dia") is not None]
    for f in usd_funds:
        if f.get("pct_mes") is not None and f["pct_mes"] >= 85:
            bullets.append(("opp",
                f"<b>Propuesta de valor en dólares — {f['n']}:</b> pctil {f['pct_mes']}° "
                f"en el mes dentro de su categoría USD. Con el contexto cambiario actual, "
                f"este fondo tiene potencial de captación entre clientes que buscan "
                f"dolarizar cartera."))

    if not bullets:
        bullets.append(("opp", "<b>Sin alertas críticas el día de hoy.</b> Todos los fondos operan dentro de parámetros normales."))

    # ── render HTML ──────────────────────────────────────────────────────────
    icon_map = {"alert": ("!", "b-alert"), "warn": ("~", "b-warn"), "opp": ("+", "b-opp")}
    label_map = {"alert": "Alerta", "warn": "Atención", "opp": "Oportunidad"}
    color_map = {"alert": "#791f1f", "warn": "#633806", "opp": "#27500a"}

    items_html = ""
    for tipo, texto in bullets:
        icon_char, icon_cls = icon_map[tipo]
        items_html += f"""<div class="bullet">
  <div class="bicon {icon_cls}">{icon_char}</div>
  <div style="flex:1">{texto}</div>
</div>\n"""

    return f"""<div class="concl">
  <div class="concl-title">Conclusiones del día — Alertas y oportunidades</div>
  {items_html}
</div>"""

# ─────────────────────────────────────────────────────────────────────────────
# QUIRON PM DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def build_quiron_dashboard(agg, bench, fecha_str, fx_mep=1400, fx_source="fallback"):
    quiron = agg[agg["is_target"] & (agg["Patrimonio"] > 0)].copy()
    if quiron.empty:
        log(f"No se encontraron fondos de '{SOC_GERENTE}' — verificá el nombre.")
        return None

    total_hoy = quiron["Patrimonio"].sum()
    total_ant = quiron["Patrimonio_Ant"].sum()
    delta_aum = total_hoy - total_ant
    delta_pct  = delta_aum / total_ant * 100 if total_ant else 0

    # attach benchmark mediana
    quiron = quiron.merge(bench, on=["Tipo","Moneda"], how="left")

    COLORS = ["#3266ad","#1d9e75","#d85a30","#639922","#7f77dd","#e8a838","#5c9bd1","#d4537e","#b4b2a9","#888780"]
    max_aum = quiron["Patrimonio"].max()

    # AUM rank within each Tipo+Moneda (1 = largest AUM)
    agg["aum_rank"] = agg.groupby(["Tipo","Moneda"])["Patrimonio"].rank(
        method="min", ascending=False, na_option="keep"
    )
    agg["aum_n"] = agg.groupby(["Tipo","Moneda"])["Patrimonio"].transform("count")
    quiron = quiron.merge(
        agg[["Fondo_Base","Tipo","Moneda","aum_rank","aum_n"]],
        on=["Fondo_Base","Tipo","Moneda"], how="left"
    )

    funds_js = []
    for i, (_, f) in enumerate(quiron.iterrows()):
        def safe(v): return round(float(v), 3) if pd.notna(v) else None
        funds_js.append({
            "n":   f["Fondo_Base"],
            "tipo": f["Tipo"], "mon": f["Moneda"],
            "aum": round(f["Patrimonio"]/1e6),
            "color": COLORS[i % len(COLORS)],
            "aum_pct": round(f["Patrimonio"]/max_aum*100),
            "dia":  safe(f["Var_Dia"]),  "mes":  safe(f["Var_Mes"]),
            "anio": safe(f["Var_Anio"]), "doce": safe(f["Var_12M"]),
            "b_dia":  safe(f.get("med_dia")),  "b_mes":  safe(f.get("med_mes")),
            "b_anio": safe(f.get("med_anio")), "b_doce": safe(f.get("med_12m")),
            "pct_dia":  round(float(f["pct_Var_Dia"]))  if pd.notna(f.get("pct_Var_Dia"))  else None,
            "pct_mes":  round(float(f["pct_Var_Mes"]))  if pd.notna(f.get("pct_Var_Mes"))  else None,
            "pct_anio": round(float(f["pct_Var_Anio"])) if pd.notna(f.get("pct_Var_Anio")) else None,
            "pct_doce": round(float(f["pct_Var_12M"]))  if pd.notna(f.get("pct_Var_12M"))  else None,
            "rank_dia":  int(f["rank_Var_Dia"])  if pd.notna(f.get("rank_Var_Dia"))  else None,
            "rank_mes":  int(f["rank_Var_Mes"])  if pd.notna(f.get("rank_Var_Mes"))  else None,
            "rank_anio": int(f["rank_Var_Anio"]) if pd.notna(f.get("rank_Var_Anio")) else None,
            "rank_doce": int(f["rank_Var_12M"])  if pd.notna(f.get("rank_Var_12M"))  else None,
            "n_dia":  int(f["n_Var_Dia"])  if pd.notna(f.get("n_Var_Dia"))  else None,
            "n_mes":  int(f["n_Var_Mes"])  if pd.notna(f.get("n_Var_Mes"))  else None,
            "n_anio": int(f["n_Var_Anio"]) if pd.notna(f.get("n_Var_Anio")) else None,
            "n_doce": int(f["n_Var_12M"])  if pd.notna(f.get("n_Var_12M"))  else None,
            "aum_rank": int(f["aum_rank"]) if pd.notna(f.get("aum_rank")) else None,
            "aum_n":    int(f["aum_n"])    if pd.notna(f.get("aum_n"))    else None,
        })

    conclusions_html = build_conclusions(funds_js, total_hoy, total_ant, delta_pct)

    # filtrar fondos con dato de rendimiento anual antes de buscar mejor/peor
    con_anio   = [f for f in funds_js if f.get("anio") is not None]
    _placeholder = {**funds_js[0], "anio": 0.0, "pct_anio": "—", "n": funds_js[0]["n"]}
    best_anio  = max(con_anio, key=lambda x: x["anio"]) if con_anio else _placeholder
    worst_anio = min(con_anio, key=lambda x: x["anio"]) if con_anio else _placeholder
    # copias para no mutar funds_js, y asegurar que pct_anio nunca sea None
    best_anio  = {**best_anio,  "pct_anio": best_anio.get("pct_anio")  or "—"}
    worst_anio = {**worst_anio, "pct_anio": worst_anio.get("pct_anio") or "—"}
    alert_show = "block" if abs(delta_pct) > 2 else "none"
    alert_color = "#fcebeb" if delta_pct < 0 else "#eaf3de"
    alert_border = "#f09595" if delta_pct < 0 else "#c0dd97"
    alert_text_color = "#791f1f" if delta_pct < 0 else "#27500a"

    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{SOC_GERENTE} AM — PM Dashboard · {fecha_str}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0efe8;color:#1a1a18;font-size:13px;line-height:1.5}}
.page{{max-width:940px;margin:0 auto;padding:1.25rem 1rem 3rem}}
header{{margin-bottom:1rem}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}}
.logo{{width:34px;height:34px;background:#1a1a18;border-radius:7px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:500;flex-shrink:0}}
.brand-name{{font-size:16px;font-weight:500}}
.brand-sub{{font-size:10px;color:#888780;margin-top:1px}}
.dbadge{{background:#fff;border:1px solid #d3d1c7;border-radius:7px;padding:4px 11px;font-size:10px;color:#888780;white-space:nowrap}}
.alert{{border-radius:8px;padding:7px 13px;font-size:11px;margin-bottom:1rem;display:none}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:1rem}}
.kpi{{background:#fff;border:1px solid #d3d1c7;border-radius:9px;padding:.8rem}}
.kl{{font-size:10px;color:#888780;margin-bottom:3px}}
.kv{{font-size:18px;font-weight:500}}
.ks{{font-size:10px;color:#888780;margin-top:1px}}
.kdown .kv{{color:#a32d2d}}.kup .kv{{color:#3b6d11}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-bottom:11px}}
.card{{background:#fff;border:1px solid #d3d1c7;border-radius:9px;padding:1rem}}
.ct{{font-size:12px;font-weight:500;margin-bottom:3px}}
.cs{{font-size:10px;color:#888780;margin-bottom:9px}}
.psel{{display:flex;gap:5px;margin-bottom:12px}}
.ps{{padding:4px 11px;font-size:11px;border:1px solid #d3d1c7;border-radius:6px;background:none;color:#888780;cursor:pointer}}
.ps.on{{background:#1a1a18;color:#fff;border-color:#1a1a18}}
table{{width:100%;border-collapse:collapse;font-size:11px}}
th{{padding:4px 7px;text-align:left;font-weight:400;color:#888780;border-bottom:1px solid #d3d1c7;white-space:nowrap}}
th.r{{text-align:right}}
td{{padding:4px 7px;border-bottom:1px solid #f0efe8;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
.badge{{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:500}}
.bg{{background:#eaf3de;color:#27500a}}.br{{background:#fcebeb;color:#791f1f}}.by{{background:#faeeda;color:#633806}}.bn{{background:#f0efe8;color:#5f5e5a}}
.hmc{{display:inline-block;min-width:52px;padding:3px 6px;border-radius:4px;text-align:center;font-size:11px;font-weight:500}}
.delta-row{{display:flex;flex-direction:column;gap:2px;margin-bottom:9px}}
.delta-lbl{{display:flex;justify-content:space-between;font-size:11px}}
.delta-track{{position:relative;height:12px;background:#f0efe8;border-radius:3px}}
.delta-zero{{position:absolute;top:0;bottom:0;width:1px;background:#b4b2a9}}
.delta-bar{{position:absolute;top:1px;height:10px;border-radius:2px}}
.note{{font-size:10px;color:#b4b2a9;margin-top:7px}}
.concl{{background:#fff;border:1px solid #d3d1c7;border-radius:9px;padding:1rem;margin-bottom:11px}}
.concl-title{{font-size:12px;font-weight:500;margin-bottom:10px}}
.bullet{{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #f0efe8;font-size:11px;line-height:1.5}}
.bullet:last-child{{border-bottom:none}}
.bicon{{flex-shrink:0;width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;margin-top:1px}}
.b-alert{{background:#fcebeb;color:#791f1f}}
.b-opp{{background:#eaf3de;color:#27500a}}
.b-warn{{background:#faeeda;color:#633806}}
.bullet b{{font-weight:500}}
canvas{{display:block;width:100%}}
footer{{text-align:center;font-size:10px;color:#b4b2a9;margin-top:1.5rem}}
@media(max-width:620px){{.kpis{{grid-template-columns:1fr 1fr}}.grid2{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="page">
<header>
<div class="hdr">
  <div style="display:flex;align-items:center;gap:9px">
    <div class="logo">{SOC_GERENTE[0].upper()}</div>
    <div><div class="brand-name">{SOC_GERENTE} Asset Management</div><div class="brand-sub">Portfolio Manager Dashboard</div></div>
  </div>
  <div class="dbadge">{fecha_str}</div>
</div>
</header>

<div class="alert" id="aum-alert" style="display:{alert_show};background:{alert_color};border:1px solid {alert_border};color:{alert_text_color}">
  {'⚠' if delta_pct < 0 else '✓'} <b>AUM {'cayó' if delta_pct < 0 else 'creció'} {abs(delta_pct):.1f}%</b> respecto al día anterior ({fmt_ars(delta_aum)} {'menos' if delta_aum<0 else 'más'}).
</div>

<div class="kpis">
  <div class="kpi {'kdown' if delta_pct<-1 else 'kup' if delta_pct>1 else ''}">
    <div class="kl">AUM total hoy</div>
    <div class="kv">{fmt_ars(total_hoy)}</div>
    <div class="ks">vs {fmt_ars(total_ant)} ayer ({delta_pct:+.1f}%)</div>
  </div>
  <div class="kpi">
    <div class="kl">Fondos activos</div>
    <div class="kv">{len(quiron)}</div>
    <div class="ks">con patrimonio &gt; 0</div>
  </div>
  <div class="kpi kup">
    <div class="kl">Mejor fondo (año)</div>
    <div class="kv" style="font-size:13px">{best_anio['n']}</div>
    <div class="ks">{(f"{best_anio['anio']:+.2f}%" if best_anio['anio'] is not None else "—")} · pctil {best_anio['pct_anio']}°</div>
  </div>
  <div class="kpi kdown">
    <div class="kl">Más rezagado (año)</div>
    <div class="kv" style="font-size:13px">{worst_anio['n']}</div>
    <div class="ks">{(f"{worst_anio['anio']:+.2f}%" if worst_anio['anio'] is not None else "—")} · pctil {worst_anio['pct_anio']}°</div>
  </div>
</div>

<div class="grid2">
<div class="card">
  <div class="ct">Composición del AUM</div>
  <canvas id="c-donut" style="height:200px"></canvas>
  <div id="dleg" style="margin-top:9px;display:flex;flex-wrap:wrap;gap:7px;font-size:10px;color:#444"></div>
</div>
<div class="card">
  <div class="ct">Posición por AUM dentro de la categoría y moneda</div>
  <div id="fund-pills"></div>
</div>
</div>

<div class="card" style="margin-bottom:11px">
  <div class="ct">Rendimiento vs benchmark (mediana de categoría)</div>
  <div class="cs">Verde = supera la mediana · Rojo = por debajo</div>
  <div class="psel">
    <button class="ps on" onclick="setHM('dia',this)">Hoy</button>
    <button class="ps" onclick="setHM('mes',this)">Mes</button>
    <button class="ps" onclick="setHM('anio',this)">Año</button>
    <button class="ps" onclick="setHM('doce',this)">12 meses</button>
  </div>
  <div style="overflow-x:auto">
  <table id="hm-table">
    <thead><tr><th>Fondo</th><th class="r">AUM</th><th class="r">Quiron</th><th class="r">Mediana</th><th class="r">Δ</th><th class="r">Ranking</th><th class="r">Percentil</th></tr></thead>
    <tbody id="hm-body"></tbody>
  </table>
  </div>
  <div class="note">Benchmark = mediana de todos los fondos de la misma categoría y moneda (outliers &gt;{OUTLIER_LIMIT}% excluidos).</div>
</div>

<div class="card" style="margin-bottom:11px">
  <div class="ct">Diferencial vs benchmark</div>
  <div class="psel">
    <button class="ps on" onclick="setD('dia',this)">Hoy</button>
    <button class="ps" onclick="setD('mes',this)">Mes</button>
    <button class="ps" onclick="setD('anio',this)">Año</button>
    <button class="ps" onclick="setD('doce',this)">12 meses</button>
  </div>
  <div id="delta-chart"></div>
</div>

{conclusions_html}
<footer>{SOC_GERENTE} Asset Management · Dashboard interno · {fecha_str} · CAFCI · Tipo de cambio MEP: ${fx_mep:,} ARS/USD (fuente: {fx_source}) · Valores sujetos a revisión</footer>
</div>

<script>
const DPR=window.devicePixelRatio||1;
const FUNDS={json.dumps(funds_js, ensure_ascii=False)};
const TOTAL_AUM={round(total_hoy)};
const PK={{dia:['dia','b_dia','pct_dia','rank_dia','n_dia'],mes:['mes','b_mes','pct_mes','rank_mes','n_mes'],anio:['anio','b_anio','pct_anio','rank_anio','n_anio'],doce:['doce','b_doce','pct_doce','rank_doce','n_doce']}};
let hmP='dia',dP='dia';

function fmt(v){{if(v>=1e9)return'$'+(v/1e9).toFixed(1)+'B';return'$'+(v/1e6).toFixed(0)+'M';}}
function badge(p){{if(p===null)return'<span class="badge bn">n/d</span>';if(p>=75)return`<span class="badge bg">pctil ${{p}}°</span>`;if(p>=40)return`<span class="badge by">pctil ${{p}}°</span>`;return`<span class="badge br">pctil ${{p}}°</span>`;}}
function hmColor(q,b){{if(b===null)return'#f0efe8';const d=q-b;if(d>=0.5)return'#c0dd97';if(d>=0.1)return'#eaf3de';if(d>=-0.1)return'#f5f5f3';if(d>=-0.5)return'#f7c1c1';return'#f09595';}}
function hmTC(q,b){{if(b===null)return'#5f5e5a';const d=q-b;if(d>=0.1)return'#27500a';if(d<=-0.1)return'#791f1f';return'#1a1a18';}}

// Donut
function drawDonut(){{
const c=document.getElementById('c-donut');
const W=c.parentElement.clientWidth-2,H=200;
c.style.width=W+'px';c.style.height=H+'px';c.width=W*DPR;c.height=H*DPR;
const ctx=c.getContext('2d');ctx.scale(DPR,DPR);
const cx=W/2,cy=H/2,R=80,r=48;let ang=-Math.PI/2;
FUNDS.forEach(f=>{{const sl=f.aum/TOTAL_AUM*1e6*Math.PI*2;
ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,R,ang,ang+sl);ctx.closePath();ctx.fillStyle=f.color;ctx.fill();
ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,r,ang,ang+sl);ctx.closePath();ctx.fillStyle='#fff';ctx.fill();
ang+=sl;}});
ctx.fillStyle='#1a1a18';ctx.font='500 14px -apple-system,sans-serif';ctx.textAlign='center';ctx.fillText(fmt(TOTAL_AUM),cx,cy+2);
ctx.fillStyle='#888780';ctx.font='10px -apple-system,sans-serif';ctx.fillText('AUM total',cx,cy+14);
document.getElementById('dleg').innerHTML=FUNDS.map(f=>`<span style="display:flex;align-items:center;gap:3px"><span style="width:8px;height:8px;border-radius:2px;background:${{f.color}};flex-shrink:0"></span>${{f.n.replace('Quiron ','').replace('Quiron','')||f.n}} ${{(f.aum/TOTAL_AUM*1e6*100).toFixed(1)}}%</span>`).join('');}}

// Fund pills
function buildPills(){{
document.getElementById('fund-pills').innerHTML=FUNDS.map(f=>
`<div style="display:flex;align-items:center;gap:7px;padding:5px 0;border-bottom:1px solid #f0efe8">
  <div style="width:7px;height:7px;border-radius:2px;background:${{f.color}};flex-shrink:0"></div>
  <div style="flex:1;min-width:0"><div style="font-size:11px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{f.n}}</div>
  <div style="font-size:10px;color:#888780">${{f.tipo}} · ${{f.mon}}</div></div>
  <div style="font-size:10px;color:#444;white-space:nowrap">${{fmt(f.aum*1e6)}}</div>
  <span class="badge bn" style="white-space:nowrap;font-size:10px">${{f.aum_rank!==null&&f.aum_n!==null?f.aum_rank+'°/'+f.aum_n:'n/d'}}</span>
</div>`).join('');}}

// Heatmap
function setHM(p,btn){{hmP=p;btn.closest('.psel').querySelectorAll('.ps').forEach(b=>b.classList.toggle('on',b===btn));renderHM();}}
function rankColor(r,n){{if(r===null||n===null)return'#5f5e5a';const pct=r/n;if(pct<=0.25)return'#27500a';if(pct<=0.5)return'#633806';return'#791f1f';}}
function rankBg(r,n){{if(r===null||n===null)return'#f0efe8';const pct=r/n;if(pct<=0.25)return'#eaf3de';if(pct<=0.5)return'#faeeda';return'#fcebeb';}}
function renderHM(){{
const [vk,bk,pk,rk,nk]=PK[hmP];
document.getElementById('hm-body').innerHTML=FUNDS.map(f=>{{
const q=f[vk],b=f[bk],pv=f[pk],rv=f[rk],nv=f[nk];
const diff=b!==null&&q!==null?q-b:null;
const bg=hmColor(q,b);const tc=hmTC(q,b);const sign=diff!==null?(diff>=0?'+':''):'';
const rankTxt=rv!==null&&nv!==null?`${{rv}}° de ${{nv}}`:'—';
return`<tr>
  <td><div style="font-size:11px;font-weight:500">${{f.n}}</div><div style="font-size:10px;color:#888780">${{f.tipo}} · ${{f.mon}}</div></td>
  <td style="text-align:right;color:#444">${{fmt(f.aum*1e6)}}</td>
  <td style="text-align:right"><span class="hmc" style="background:${{bg}};color:${{tc}}">${{q!==null?q.toFixed(3)+'%':'—'}}</span></td>
  <td style="text-align:right;color:#888780">${{b!==null?b.toFixed(3)+'%':'—'}}</td>
  <td style="text-align:right;font-weight:500;color:${{diff!==null?(diff>=0?'#3b6d11':'#a32d2d'):'#888'}}">${{diff!==null?sign+diff.toFixed(3)+'%':'—'}}</td>
  <td style="text-align:right"><span class="hmc" style="background:${{rankBg(rv,nv)}};color:${{rankColor(rv,nv)}};min-width:60px">${{rankTxt}}</span></td>
  <td style="text-align:right">${{badge(pv)}}</td>
</tr>`;}}).join('');}}

// Delta chart
function setD(p,btn){{dP=p;btn.closest('.psel').querySelectorAll('.ps').forEach(b=>b.classList.toggle('on',b===btn));renderDelta();}}
function renderDelta(){{
const [vk,bk]=PK[dP];
const items=FUNDS.map(f=>{{const d=f[bk]!==null&&f[vk]!==null?f[vk]-f[bk]:null;return{{n:f.n,d,color:f.color}};}}).filter(x=>x.d!==null);
const maxD=Math.max(...items.map(x=>Math.abs(x.d)))*1.1||1;
document.getElementById('delta-chart').innerHTML=items.map(x=>{{
const p=Math.abs(x.d)/maxD*45;const pos=x.d>=0;const color=pos?'#639922':'#d85a30';
return`<div class="delta-row">
  <div class="delta-lbl"><span style="font-size:11px">${{x.n}}</span><span style="color:${{color}};font-weight:500">${{pos?'+':''}}${{x.d.toFixed(3)}}%</span></div>
  <div class="delta-track"><div class="delta-zero" style="left:50%"></div>
  <div class="delta-bar" style="left:${{pos?50:50-p}}%;width:${{p}}%;background:${{color}}"></div></div>
</div>`;}}).join('');}}

window.addEventListener('DOMContentLoaded',()=>{{drawDonut();buildPills();renderHM();renderDelta();}});
window.addEventListener('resize',()=>drawDonut());
</script></body></html>"""
    return html

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today()
    fecha_str = today.strftime("%d/%m/%Y")
    date_slug  = today.strftime("%Y%m%d")

    xlsx_path = OUTPUT_DIR / f"planilla_{date_slug}.xlsx"

    # 1. Descargar
    if not download_xlsx(DOWNLOAD_URL, xlsx_path):
        log("No se pudo descargar. Verificá tu conexión o si CAFCI publicó la planilla.")
        sys.exit(1)

    # 2. Obtener tipo de cambio MEP
    FX_MEP, fx_source = get_mep(FX_MEP_FALLBACK)
    log(f"Tipo de cambio USD MEP: ${FX_MEP:,} ARS (fuente: {fx_source})")
    df  = load_data(xlsx_path, FX_MEP)
    agg, bench = aggregate(df)
    n_usd = (df["Moneda"].isin(["USD","USB"])).sum()
    log(f"Fondos únicos: {len(agg)} | Patrimonio total ARS equiv.: {fmt_ars(agg['Patrimonio'].sum())} ({n_usd} clases USD/USB convertidas)")

    # 3. Dashboard general
    html_gen = build_general_dashboard(agg, bench, fecha_str, fx_mep=FX_MEP, fx_source=fx_source)
    path_gen = OUTPUT_DIR / f"CAFCI_Dashboard_{date_slug}.html"
    path_gen.write_text(html_gen, encoding="utf-8")
    log(f"Dashboard general guardado: {path_gen}")

    # 4. Dashboard Quiron PM
    html_pm = build_quiron_dashboard(agg, bench, fecha_str, fx_mep=FX_MEP, fx_source=fx_source)
    if html_pm:
        path_pm = OUTPUT_DIR / f"Quiron_PM_Dashboard_{date_slug}.html"
        path_pm.write_text(html_pm, encoding="utf-8")
        log(f"Dashboard Quiron PM guardado: {path_pm}")

    log("¡Listo!")
    log(f"Carpeta de salida: {OUTPUT_DIR.resolve()}")

if __name__ == "__main__":
    main()

# =============================================================================
# CÓMO PROGRAMAR LA EJECUCIÓN AUTOMÁTICA
# =============================================================================
#
# ── Mac / Linux (crontab) ────────────────────────────────────────────────────
#
#   1. Abrí la terminal y ejecutá:
#        crontab -e
#
#   2. Agregá esta línea (ajustá la ruta al script y al python):
#        0 21 * * 1-5 /usr/bin/python3 /Users/TU_USUARIO/cafci_dashboard_update.py >> /Users/TU_USUARIO/cafci_log.txt 2>&1
#
#      Explicación:  0 21 * * 1-5  = a las 21:00, lunes a viernes
#
#   3. Para ver el path de python3 ejecutá:  which python3
#
# ── Windows (Task Scheduler) ─────────────────────────────────────────────────
#
#   1. Abrí "Programador de tareas" (buscalo en el menú inicio)
#   2. "Crear tarea básica" → ponele nombre "CAFCI Dashboard"
#   3. Desencadenador: Diariamente → hora 21:00
#   4. Acción: Iniciar un programa
#        Programa: C:\Python312\python.exe  (o donde esté tu python)
#        Argumentos: C:\ruta\cafci_dashboard_update.py
#   5. Guardá y listo.
#
# ── Verificar que funciona ───────────────────────────────────────────────────
#
#   Corré manualmente primero:
#       python3 cafci_dashboard_update.py
#
#   Los archivos se generan en la carpeta  ./dashboards/
#
# =============================================================================
