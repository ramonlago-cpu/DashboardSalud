"""
procesar_salud_json.py
Procesa los ficheros Salud-YYYY-MM-DD.json de Health Auto Export
y devuelve un DataFrame diario con todas las métricas de salud.

Reemplaza procesar_datos.py (basado en CSV) con datos más ricos y estructurados.
"""
import json
import os
import re
import pandas as pd
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _suma(data, campo='qty'):
    return sum(d.get(campo, 0) or 0 for d in data)

def _media(data, campo='qty'):
    vals = [d.get(campo, 0) or 0 for d in data if d.get(campo) is not None]
    return sum(vals) / len(vals) if vals else None

def _maximo(data, campo='qty'):
    vals = [d.get(campo, 0) or 0 for d in data if d.get(campo) is not None]
    return max(vals) if vals else None

def _primero(data, campo='qty'):
    return data[0].get(campo) if data else None


# ──────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def analizar_salud_json(rutas_json: list) -> pd.DataFrame:
    """
    Lee una lista de ficheros Salud-YYYY-MM-DD.json y devuelve un DataFrame
    con una fila por día y todas las métricas disponibles.

    Columnas de salida (compatibles con las antiguas del CSV donde se pueda):
      fecha, pasos, distancia_km,
      sueno_total_h, sueno_profundo_h, sueno_rem_h, sueno_core_h, sueno_despierto_h,
      fc_reposo, fc_media, fc_max, fc_caminando,
      hrv_ms,
      freq_respiratoria, alteraciones_respiracion,
      spo2_pct,
      temp_muneca,
      energia_activa_kj, energia_reposo_kj, calorias_totales_kcal,
      minutos_ejercicio, tiempo_de_pie_min, horas_de_pie,
      luz_solar_min,
      vo2max,
      ruido_ambiental_db
    """
    registros = []

    for ruta in rutas_json:
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            continue

        # Extraer la fecha del nombre del fichero (Salud-YYYY-MM-DD.json)
        nombre = os.path.basename(ruta)
        m = re.search(r'(\d{4}-\d{2}-\d{2})', nombre)
        if not m:
            continue
        try:
            fecha = datetime.strptime(m.group(1), '%Y-%m-%d').date()
        except ValueError:
            continue

        # Construir diccionario métrica → lista de puntos
        metricas = {}
        for item in raw.get('data', {}).get('metrics', []):
            metricas[item['name']] = item.get('data', [])

        rec = {'fecha': fecha}

        # ── Actividad física ──────────────────────────────────────────────────
        rec['pasos']          = round(_suma(metricas.get('step_count', [])))
        rec['distancia_km']   = round(_suma(metricas.get('walking_running_distance', [])), 2)
        rec['minutos_ejercicio'] = round(_suma(metricas.get('apple_exercise_time', [])), 1)
        rec['tiempo_de_pie_min'] = round(_suma(metricas.get('apple_stand_time', [])), 1)
        rec['horas_de_pie']   = round(_suma(metricas.get('apple_stand_hour', [])), 0)
        luz = _suma(metricas.get('time_in_daylight', []))
        rec['luz_solar_min']  = round(luz, 1) if luz else None

        # ── Energía ───────────────────────────────────────────────────────────
        e_act = _suma(metricas.get('active_energy', []))
        e_rep = _suma(metricas.get('basal_energy_burned', []))
        rec['energia_activa_kj']   = round(e_act, 1)
        rec['energia_reposo_kj']   = round(e_rep, 1)
        rec['calorias_totales_kcal'] = round((e_act + e_rep) / 4.184, 0) if (e_act + e_rep) else None

        # ── Frecuencia cardíaca ───────────────────────────────────────────────
        hr_data = metricas.get('heart_rate', [])
        rec['fc_media']       = round(_media(hr_data, 'Avg'), 0) if _media(hr_data, 'Avg') else None
        rec['fc_max']         = _maximo(hr_data, 'Max')
        rec['fc_reposo']      = _primero(metricas.get('resting_heart_rate', []))
        fc_cam = _primero(metricas.get('walking_heart_rate_average', []))
        rec['fc_caminando']   = round(fc_cam, 0) if fc_cam else None

        # ── HRV ───────────────────────────────────────────────────────────────
        hrv = _media(metricas.get('heart_rate_variability', []))
        rec['hrv_ms'] = round(hrv, 1) if hrv else None

        # ── Respiración y SpO2 ───────────────────────────────────────────────
        rr = _media(metricas.get('respiratory_rate', []))
        rec['freq_respiratoria'] = round(rr, 1) if rr else None

        bd = _primero(metricas.get('breathing_disturbances', []))
        rec['alteraciones_respiracion'] = round(bd, 0) if bd else None

        spo2 = _media(metricas.get('blood_oxygen_saturation', []))
        rec['spo2_pct'] = round(spo2, 1) if spo2 else None

        # ── Temperatura de muñeca ─────────────────────────────────────────────
        tw = _primero(metricas.get('apple_sleeping_wrist_temperature', []))
        rec['temp_muneca'] = round(tw, 2) if tw else None

        # ── Sueño ─────────────────────────────────────────────────────────────
        sleep_data = metricas.get('sleep_analysis', [])
        if sleep_data:
            s = sleep_data[0]
            rec['sueno_total_h']     = round(s.get('totalSleep', 0) or 0, 2)
            rec['sueno_profundo_h']  = round(s.get('deep',  0) or 0, 2)
            rec['sueno_rem_h']       = round(s.get('rem',   0) or 0, 2)
            rec['sueno_core_h']      = round(s.get('core',  0) or 0, 2)
            rec['sueno_despierto_h'] = round(s.get('awake', 0) or 0, 2)
            # Hora de dormir y despertar
            try:
                hora_str = s.get('sleepStart', '')
                rec['hora_dormir'] = datetime.strptime(
                    hora_str[:19], '%Y-%m-%d %H:%M:%S'
                ).strftime('%H:%M') if hora_str else None
            except Exception:
                rec['hora_dormir'] = None
            try:
                hora_str = s.get('sleepEnd', '')
                rec['hora_despertar'] = datetime.strptime(
                    hora_str[:19], '%Y-%m-%d %H:%M:%S'
                ).strftime('%H:%M') if hora_str else None
            except Exception:
                rec['hora_despertar'] = None
        else:
            for col in ['sueno_total_h', 'sueno_profundo_h', 'sueno_rem_h',
                        'sueno_core_h', 'sueno_despierto_h', 'hora_dormir', 'hora_despertar']:
                rec[col] = None

        # ── VO2max (aparece esporádicamente) ──────────────────────────────────
        vo2 = _primero(metricas.get('vo2_max', []))
        rec['vo2max'] = round(vo2, 1) if vo2 else None

        # ── Ruido ambiental ───────────────────────────────────────────────────
        ruido = _media(metricas.get('environmental_audio_exposure', []))
        rec['ruido_ambiental_db'] = round(ruido, 1) if ruido else None

        registros.append(rec)

    if not registros:
        return pd.DataFrame()

    df = pd.DataFrame(registros)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df = df.sort_values('fecha').reset_index(drop=True)
    return df
