"""
procesar_actividades_json.py
Procesa los ficheros Actividades-YYYY-MM-DD.json de Health Auto Export
y devuelve una lista de dicts (y opcionalmente un DataFrame) con todos
los workouts, compatible con lo que app.py espera para las tarjetas.

Reemplaza historico_entrenamientos.csv de HealthFitExporter.
"""
import json
import os
import re
import math
import glob
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# MAPEO DE NOMBRES → TIPO DE DEPORTE NORMALIZADO
# ──────────────────────────────────────────────────────────────────────────────
_NOMBRE_A_DEPORTE = {
    # Running / marcha
    'exterior ejecutar':          'running',
    'ejecutar':                   'running',
    'running':                    'running',
    'correr':                     'running',
    'caminata':                   'walking',
    'marcha':                     'walking',
    'walking':                    'walking',
    'senderismo':                 'hiking',
    'hiking':                     'hiking',
    # Ciclismo
    'ciclismo':                   'cycling',
    'cycling':                    'cycling',
    'ciclismo en exterior':       'cycling',
    'ciclismo en interior':       'indoor_cycling',
    'bicicleta estática':         'indoor_cycling',
    # Natación
    'natación':                   'swimming',
    'swimming':                   'swimming',
    # Fuerza / funcional
    'entrenamiento cruzado':      'cross_training',
    'cross training':             'cross_training',
    'functional strength training':'functional_strength_training',
    'fuerza funcional':           'functional_strength_training',
    'entrenamiento de fuerza':    'strength_training',
    'strength training':          'strength_training',
    'fuerza':                     'strength_training',
    'pesas':                      'strength_training',
    # HIIT / aeróbico
    'hiit':                       'hiit',
    'aeróbico':                   'aerobics',
    # Yoga / mente-cuerpo
    'yoga':                       'yoga',
    'pilates':                    'pilates',
    'meditación':                 'mindfulness',
    # Deportes
    'tenis':                      'tennis',
    'pádel':                      'padel',
    'fútbol':                     'soccer',
    'baloncesto':                 'basketball',
    'esquí':                      'skiing',
    'surf':                       'surfing',
    'escalada':                   'climbing',
    # Remo / elíptica
    'remo':                       'rowing',
    'rowing':                     'rowing',
    'elíptica':                   'elliptical',
    'elliptical':                 'elliptical',
}


def _normalizar_deporte(nombre: str) -> str:
    """Convierte el nombre libre de Apple Health al tipo normalizado."""
    clave = nombre.strip().lower()
    # Búsqueda exacta primero
    if clave in _NOMBRE_A_DEPORTE:
        return _NOMBRE_A_DEPORTE[clave]
    # Búsqueda parcial
    for patron, tipo in _NOMBRE_A_DEPORTE.items():
        if patron in clave or clave in patron:
            return tipo
    # Sin coincidencia → usar nombre limpio como clave
    return re.sub(r'\s+', '_', clave)


def _calcular_trimp(fc_media: float, fc_max: float, fc_reposo: float,
                    duracion_min: float) -> float:
    """
    TRIMP (Training Impulse) de Banister.
    HR_ratio = (FCmedia - FCreposo) / (FCmax - FCreposo)
    TRIMP = duracion × HR_ratio × e^(1.92 × HR_ratio)
    """
    if not (fc_media > 0 and fc_max > fc_reposo and duracion_min > 0):
        return 0.0
    hr_ratio = (fc_media - fc_reposo) / (fc_max - fc_reposo)
    hr_ratio = max(0.0, min(1.0, hr_ratio))
    return round(duracion_min * hr_ratio * math.exp(1.92 * hr_ratio), 1)


def _fmt_ritmo(distancia_km: float, duracion_min: float) -> str:
    """Devuelve ritmo en formato mm:ss /km."""
    if distancia_km <= 0 or duracion_min <= 0:
        return ''
    seg_km = (duracion_min * 60) / distancia_km
    m, s = divmod(int(seg_km), 60)
    return f"{m}:{s:02d}"


def _qty(obj, default=0.0):
    """Extrae .qty de un dict {qty, units}, o devuelve default."""
    if isinstance(obj, dict):
        return obj.get('qty', default) or default
    return default


# ──────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def cargar_actividades(dir_actividades: str,
                       fc_reposo_default: float = 55.0,
                       fc_max_global: float = 0.0) -> list:
    """
    Lee todos los Actividades-*.json de `dir_actividades` y devuelve
    una lista de dicts, uno por workout, ordenada cronológicamente.

    Cada dict tiene:
      fecha_inicio (datetime), fecha_fin (datetime), deporte (str),
      nombre_original (str), location (str),
      distancia_km, duracion_min, velocidad_kmh,
      fc_media, fc_max, fc_min,
      calorias_kcal, energia_activa_kj,
      cadencia_media, desnivel_positivo,
      temperatura, humedad,
      carga_entreno (TRIMP), ritmo (str),
      # series temporales (listas de dicts):
      heartRateData, activeEnergy, heartRateRecovery, stepCount
    """
    ficheros = sorted(glob.glob(os.path.join(dir_actividades, 'Actividades-*.json')))
    workouts = []

    for ruta in ficheros:
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            continue

        for w in raw.get('data', {}).get('workouts', []):
            try:
                # ── Timestamps ───────────────────────────────────────────
                start_str = w.get('start', '')
                end_str   = w.get('end',   '')
                fecha_ini = datetime.strptime(start_str[:19], '%Y-%m-%d %H:%M:%S')
                fecha_fin = datetime.strptime(end_str[:19],   '%Y-%m-%d %H:%M:%S')

                # ── Resumen ───────────────────────────────────────────────
                duracion_s   = w.get('duration', 0) or 0
                duracion_min = duracion_s / 60

                dist_km = _qty(w.get('distance'))
                fc_avg  = _qty(w.get('heartRate', {}).get('avg'))
                fc_max  = _qty(w.get('heartRate', {}).get('max'))
                fc_min  = _qty(w.get('heartRate', {}).get('min'))
                # Si FC no está en heartRate, intentar avgHeartRate / maxHeartRate
                if fc_avg == 0:
                    fc_avg = _qty(w.get('avgHeartRate'))
                if fc_max == 0:
                    fc_max = _qty(w.get('maxHeartRate'))

                ae_kj   = _qty(w.get('activeEnergyBurned'))
                cal     = round(ae_kj / 4.184, 0) if ae_kj else 0
                vel     = _qty(w.get('speed'))
                cadencia = _qty(w.get('stepCadence'))
                desnivel = _qty(w.get('elevationUp'))
                temp    = _qty(w.get('temperature'))
                hum     = _qty(w.get('humidity'))

                nombre   = w.get('name', 'Actividad')
                deporte  = _normalizar_deporte(nombre)
                location = w.get('location', '')

                # FC máxima global (se actualiza si encontramos un nuevo máximo)
                nonlocal_fcmax = fc_max_global
                if fc_max > nonlocal_fcmax:
                    nonlocal_fcmax = fc_max

                # TRIMP
                trimp = _calcular_trimp(fc_avg, fc_max, fc_reposo_default, duracion_min)

                # Ritmo
                ritmo_str = _fmt_ritmo(dist_km, duracion_min) if deporte in (
                    'running', 'walking', 'hiking') else ''

                workouts.append({
                    'fecha_inicio':      fecha_ini,
                    'fecha_fin':         fecha_fin,
                    'deporte':           deporte,
                    'nombre_original':   nombre,
                    'location':          location,
                    'distancia_km':      round(dist_km, 2),
                    'duracion_min':      round(duracion_min, 1),
                    'velocidad_kmh':     round(vel, 2),
                    'fc_media':          round(fc_avg, 0) if fc_avg else 0,
                    'fc_max':            round(fc_max, 0) if fc_max else 0,
                    'fc_min':            round(fc_min, 0) if fc_min else 0,
                    'calorias_kcal':     int(cal),
                    'energia_activa_kj': round(ae_kj, 1),
                    'cadencia_media':    round(cadencia, 0) if cadencia else 0,
                    'desnivel_positivo': round(desnivel, 0) if desnivel else 0,
                    'temperatura':       round(temp, 1) if temp else 0,
                    'humedad':           round(hum, 0) if hum else 0,
                    'carga_entreno':     trimp,
                    'ritmo':             ritmo_str,
                    # Series temporales — usadas por las tarjetas expandidas
                    'route':             w.get('route', []),
                    'splits':            w.get('splits', []),
                    'heartRateData':     w.get('heartRateData', []),
                    'activeEnergy':      w.get('activeEnergy', []),
                    'heartRateRecovery': w.get('heartRateRecovery', []),
                    'stepCount':         w.get('stepCount', []),
                    # Raw id para caché
                    '_id':               w.get('id', ''),
                })
            except Exception:
                continue

    # Ordenar cronológicamente (más recientes primero para la vista)
    workouts.sort(key=lambda x: x['fecha_inicio'], reverse=True)
    return workouts
