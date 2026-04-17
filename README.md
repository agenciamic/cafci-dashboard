# 📊 CAFCI Dashboard — Quiron AM

Dashboard automático de Fondos Comunes de Inversión que se actualiza todos los días hábiles y se publica como página web gratuita usando **GitHub Actions + GitHub Pages**.

---

## 🚀 Cómo publicarlo (paso a paso)

### Paso 1 — Crear el repositorio en GitHub

1. Andá a [github.com](https://github.com) e iniciá sesión (o creá una cuenta gratis)
2. Hacé clic en **"New repository"** (botón verde arriba a la derecha)
3. Nombre del repo: `cafci-dashboard` (o el que quieras)
4. **Importante**: marcalo como **Public** (GitHub Pages es gratis solo para repos públicos)
5. Hacé clic en **"Create repository"**

---

### Paso 2 — Subir los archivos

Tenés dos opciones:

#### Opción A: Desde la web (sin instalar nada)
1. En tu nuevo repositorio, hacé clic en **"uploading an existing file"**
2. Subí todos estos archivos de una vez:
   - `cafci_dashboard_update.py`
   - `generate_index.py`
   - `.github/workflows/update_dashboard.yml`
3. Hacé clic en **"Commit changes"**

#### Opción B: Con Git desde la terminal
```bash
git clone https://github.com/TU_USUARIO/cafci-dashboard.git
cd cafci-dashboard
# copiá los archivos acá adentro
git add .
git commit -m "Setup inicial"
git push origin main
```

---

### Paso 3 — Activar GitHub Pages

1. En tu repositorio, andá a **Settings** (pestaña de configuración)
2. En el menú izquierdo, hacé clic en **"Pages"**
3. En "Source", seleccioná **"Deploy from a branch"**
4. En "Branch", seleccioná **`main`** y la carpeta **`/docs`**
5. Hacé clic en **"Save"**

Después de ~2 minutos, tu página va a estar disponible en:
```
https://TU_USUARIO.github.io/cafci-dashboard/
```

---

### Paso 4 — Hacer una prueba manual

Para verificar que todo funciona antes de esperar el horario automático:

1. En tu repositorio, hacé clic en la pestaña **"Actions"**
2. En el panel izquierdo, hacé clic en **"Actualizar Dashboard CAFCI"**
3. Hacé clic en **"Run workflow"** → **"Run workflow"** (botón verde)
4. Esperá ~2-3 minutos hasta que aparezca un tilde verde ✅
5. Visitá tu página para ver los dashboards generados

---

## ⏰ Horario de actualización automática

El workflow corre automáticamente:
- **Días**: lunes a viernes
- **Hora**: 21:00 hs Argentina (ART)

Nota: GitHub a veces ejecuta los schedules con hasta 15-30 minutos de retraso cuando hay mucho tráfico. Esto es normal y no afecta el resultado.

---

## 📁 Estructura del proyecto

```
cafci-dashboard/
├── .github/
│   └── workflows/
│       └── update_dashboard.yml   ← Automatización (no tocar)
├── docs/                          ← Se genera automáticamente
│   ├── index.html                 ← Página principal
│   ├── general.html               ← Dashboard mercado (última versión)
│   ├── quiron.html                ← Dashboard Quiron (última versión)
│   └── CAFCI_Dashboard_YYYYMMDD.html  ← Historial
├── dashboards/                    ← Archivos temporales de trabajo
├── cafci_dashboard_update.py      ← Script principal
└── generate_index.py              ← Genera la página de inicio
```

---

## ❓ Preguntas frecuentes

**¿Es realmente gratis?**
Sí. GitHub Free incluye 2.000 minutos de Actions por mes. El script tarda ~1-2 minutos por ejecución, así que en 20 días hábiles usa ~40 minutos. Muy lejos del límite.

**¿El historial se acumula?**
Sí. Cada día se agrega un archivo con la fecha, y la página principal muestra los últimos 20.

**¿Qué pasa si CAFCI no publica la planilla ese día?**
El script reintenta 5 veces y luego falla. El workflow queda marcado en rojo pero no borra los dashboards anteriores.

**¿Puedo cambiar el horario?**
Sí, editá la línea `cron` en `.github/workflows/update_dashboard.yml`. Usá [crontab.guru](https://crontab.guru) para generar el formato correcto. Recordá que GitHub usa UTC, que es ART+3.

**¿El repo tiene que ser público?**
Para usar GitHub Pages gratis, sí. Si querés que sea privado, necesitás GitHub Pro (~$4/mes). Alternativa: los datos de CAFCI son públicos de todas formas.

---

## 🛠 Modificar parámetros

Editá estas variables al inicio de `cafci_dashboard_update.py`:

```python
SOC_GERENTE    = "Quiron"   # nombre de tu sociedad gerente
FX_MEP_FALLBACK = 1400      # tipo de cambio de respaldo
OUTLIER_LIMIT  = 200        # % máximo para excluir outliers
```
