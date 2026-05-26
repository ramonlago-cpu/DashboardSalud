import streamlit as st
import plotly.express as px
import pandas as pd
import dropbox
import os
import glob
from procesar_datos import analizar_salud_csv

st.set_page_config(page_title="Mi Dashboard de Salud V3.0", layout="wide")

# ==========================================
# CONFIGURACIÓN DE DROPBOX Y RUTAS LOCALES
# ==========================================

CARPETA_DROPBOX_CSV = "/Aplicaciones/Health Auto Export/Health Auto Export/AppleHealthExport" 
CARPETA_DROPBOX_FIT = "/Aplicaciones/HealthFitExporter" 

DIR_LOCAL_CSV = "datos_locales/csv"
DIR_LOCAL_FIT = "datos_locales/fit"

os.makedirs(DIR_LOCAL_CSV, exist_ok=True)
os.makedirs(DIR_LOCAL_FIT, exist_ok=True)

@st.cache_resource
def iniciar_dropbox():
    return dropbox.Dropbox(
        app_key=st.secrets["DROPBOX_APP_KEY"],
        app_secret=st.secrets["DROPBOX_APP_SECRET"],
        oauth2_refresh_token=st.secrets["DROPBOX_REFRESH_TOKEN"]
    )

def sincronizar_carpeta(dbx, ruta_dbx, ruta_local, extension):
    ruta_api = "" if ruta_dbx == "/" else ruta_dbx
    nuevos = 0
    try:
        resultado = dbx.files_list_folder(ruta_api)
        archivos_nube = [e for e in resultado.entries if isinstance(e, dropbox.files.FileMetadata) and e.name.endswith(extension)]
        
        for entrada in archivos_nube:
            ruta_descarga = os.path.join(ruta_local, entrada.name)
            necesita_descarga = True
            
            # Si el archivo ya existe, comprobamos si el de Dropbox es diferente (pesa distinto)
            if os.path.exists(ruta_descarga):
                if os.path.getsize(ruta_descarga) == entrada.size:
                    necesita_descarga = False
                    
            if necesita_descarga:
                dbx.files_download_to_file(ruta_descarga, entrada.path_lower)
                nuevos += 1
        return nuevos
    except Exception as e:
        st.error(f"Error sincronizando la ruta {ruta_dbx}: {e}")
        return 0

@st.cache_data(show_spinner=False)
def cargar_datos_locales():
    # 1. Rutas de salud
    rutas_csv = glob.glob(os.path.join(DIR_LOCAL_CSV, "*.csv"))
    
    # 2. Ruta de tu nuevo archivo maestro de entrenamientos (generado en tu PC)
    ruta_historico = os.path.join(DIR_LOCAL_FIT, "historico_entrenamientos.csv")
    entrenos_data = []
    
    if os.path.exists(ruta_historico):
        df_historico = pd.read_csv(ruta_historico)
        entrenos_data = df_historico.to_dict('records')
        
    return rutas_csv, entrenos_data

# ==========================================
# MOTOR DE SINCRONIZACIÓN
# ==========================================
st.title("🏃‍♂️ Dashboard de Salud y Rendimiento")

dbx = iniciar_dropbox()
with st.spinner("Sincronizando archivos con Dropbox... 🔄"):
    # Sincronizamos la salud
    nuevos_csv = sincronizar_carpeta(dbx, CARPETA_DROPBOX_CSV, DIR_LOCAL_CSV, ".csv")
    
    # 🔥 EL GRAN CAMBIO: Buscamos únicamente ".csv" en la carpeta donde tienes los entrenos
    nuevos_fit = sincronizar_carpeta(dbx, CARPETA_DROPBOX_FIT, DIR_LOCAL_FIT, ".csv")
    
    if nuevos_csv > 0 or nuevos_fit > 0:
        st.toast(f"✅ ¡Nuevos datos! Actualizados {nuevos_csv + nuevos_fit} archivos.")
        cargar_datos_locales.clear()

with st.spinner("Cargando datos históricos... 🚀"):
    archivos_csv_locales, datos_entrenos = cargar_datos_locales()

# ==========================================
# SECCIÓN 1: SALUD, RECUPERACIÓN Y SUEÑO
# ==========================================
st.header("📊 Análisis de Salud General")

if archivos_csv_locales:
    df_salud = analizar_salud_csv(archivos_csv_locales)
    
    if not df_salud.empty:
        st.markdown("### 📅 Filtro de Periodo")
        opcion_periodo_salud = st.radio(
            "Selecciona el periodo a analizar:",
            ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"],
            horizontal=True, key="filtro_salud"
        )
        
        fecha_maxima_salud = df_salud.index.max()
        if opcion_periodo_salud == "Últimos 30 días":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=30)
        elif opcion_periodo_salud == "Últimos 3 meses":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=90)
        elif opcion_periodo_salud == "Este Año":
            fecha_filtro_salud = pd.Timestamp(year=fecha_maxima_salud.year, month=1, day=1)
        else:
            fecha_filtro_salud = df_salud.index.min()
            
        df_salud_filtrado = df_salud[df_salud.index >= fecha_filtro_salud].copy()
        
        inicio_pasado_salud = fecha_filtro_salud - pd.Timedelta(days=365)
        fin_pasado_salud = fecha_maxima_salud - pd.Timedelta(days=365)
        df_salud_pasado = df_salud[(df_salud.index >= inicio_pasado_salud) & (df_salud.index <= fin_pasado_salud)]
        
        media_pasos = df_salud_filtrado['pasos'].mean() if 'pasos' in df_salud_filtrado.columns else 0
        fc_media_global = df_salud_filtrado['fc_media'].mean() if 'fc_media' in df_salud_filtrado.columns else 0
        hrv_medio = df_salud_filtrado['hrv'].mean() if 'hrv' in df_salud_filtrado.columns else 0
        spo2_medio = df_salud_filtrado['spo2'].mean() if 'spo2' in df_salud_filtrado.columns else 0
        sueno_medio = df_salud_filtrado['sueno_total'].mean() if 'sueno_total' in df_salud_filtrado.columns else 0

        pasos_pasado = df_salud_pasado['pasos'].mean() if not df_salud_pasado.empty and 'pasos' in df_salud_pasado.columns else 0
        fc_pasado = df_salud_pasado['fc_media'].mean() if not df_salud_pasado.empty and 'fc_media' in df_salud_pasado.columns else 0
        hrv_pasado = df_salud_pasado['hrv'].mean() if not df_salud_pasado.empty and 'hrv' in df_salud_pasado.columns else 0
        spo2_pasado = df_salud_pasado['spo2'].mean() if not df_salud_pasado.empty and 'spo2' in df_salud_pasado.columns else 0
        sueno_pasado = df_salud_pasado['sueno_total'].mean() if not df_salud_pasado.empty and 'sueno_total' in df_salud_pasado.columns else 0

        st.markdown(f"### ⚖️ Promedios Diarios ({opcion_periodo_salud})")
        c1, c2, c3, c4, c5 = st.columns(5)
        
        dif_pasos = f"{media_pasos - pasos_pasado:,.0f}" if pasos_pasado > 0 else None
        c1.metric("🚶‍♂️ Pasos / día", f"{media_pasos:,.0f}", dif_pasos)
        
        dif_fc = f"{fc_media_global - fc_pasado:.0f} lpm" if fc_pasado > 0 else None
        c2.metric("❤️ FC Media", f"{fc_media_global:.0f} lpm", dif_fc, delta_color="inverse")
        
        dif_hrv = f"{hrv_medio - hrv_pasado:.0f} ms" if hrv_pasado > 0 else None
        c3.metric("🔋 HRV Medio", f"{hrv_medio:.0f} ms", dif_hrv)
        
        dif_spo2 = f"{(spo2_medio - spo2_pasado) * 100 if spo2_medio < 1 else (spo2_medio - spo2_pasado):.1f} %" if spo2_pasado > 0 else None
        c4.metric("🩸 SpO2 Promedio", f"{spo2_medio * 100 if spo2_medio < 1 else spo2_medio:.1f} %", dif_spo2)
        
        dif_sueno = f"{sueno_medio - sueno_pasado:.1f} h" if sueno_pasado > 0 else None
        c5.metric("💤 Sueño / día", f"{sueno_medio:.1f} h", dif_sueno)
            
        st.divider()
        
        st.markdown("### 🚶‍♂️ Evolución de Actividad (Pasos Diarios)")
        if 'pasos' in df_salud_filtrado.columns:
            import plotly.graph_objects as go
            fig_pasos = go.Figure()
            fig_pasos.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos'], 
                                           mode='lines', name='Pasos Diarios', 
                                           line=dict(color='#636EFA', width=1), 
                                           fill='tozeroy', fillcolor='rgba(99, 110, 250, 0.2)'))
            if 'pasos_tendencia' in df_salud_filtrado.columns:
                fig_pasos.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos_tendencia'], 
                                               mode='lines', name='Media Semanal', 
                                               line=dict(color='#deff9a', width=4)))
            fig_pasos.update_layout(margin=dict(l=0, r=0, t=30, b=0),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_pasos, width='stretch')
            
        st.divider()

        st.markdown("### 📉 Profundización en Tendencias")
        tab1, tab2, tab3, tab4 = st.tabs(["❤️ Corazón y HRV", "💤 Análisis del Sueño", "🔥 Actividad", "🔀 Matriz de Correlación"])
        
        with tab1:
            col_fc, col_hrv = st.columns(2)
            with col_fc:
                if 'fc_media' in df_salud_filtrado.columns:
                    fig_fc = px.line(df_salud_filtrado, x=df_salud_filtrado.index, y=['fc_media', 'fc_media_tendencia'], title="Frecuencia Cardíaca Media", color_discrete_sequence=['#FF4B4B', '#8B0000'])
                    st.plotly_chart(fig_fc, width='stretch')
            with col_hrv:
                if 'hrv' in df_salud_filtrado.columns:
                    fig_hrv = px.line(df_salud_filtrado, x=df_salud_filtrado.index, y=['hrv', 'hrv_tendencia'], title="Variabilidad (HRV)", color_discrete_sequence=['#00CC96', '#006400'])
                    st.plotly_chart(fig_hrv, width='stretch')

        with tab2:
            if all(col in df_salud_filtrado.columns for col in ['sueno_total', 'sueno_profundo', 'sueno_rem']):
                import plotly.graph_objects as go
                fig_sueno = go.Figure()
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_total'] - df_salud_filtrado['sueno_profundo'] - df_salud_filtrado['sueno_rem']
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_ligero'].clip(lower=0)
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_profundo'], name='Profundo', marker_color='#1f77b4'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_rem'], name='REM', marker_color='#9467bd'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_ligero'], name='Ligero', marker_color='#aec7e8'))
                fig_sueno.update_layout(barmode='stack', title="Fases del Sueño por Noches", yaxis_title="Horas")
                st.plotly_chart(fig_sueno, width='stretch')

        with tab3:
            if 'pasos' in df_salud_filtrado.columns:
                fig_pasos = go.Figure()
                fig_pasos.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos'], name='Pasos', marker_color='#636EFA', opacity=0.6))
                fig_pasos.update_layout(margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_pasos, width='stretch')
                
        with tab4:
            st.markdown("**🔍 Cruce de Variables: Descubriendo Causalidades**")
            cols_analisis = [c for c in ['sueno_total', 'sueno_profundo', 'hrv', 'fc_media', 'pasos'] if c in df_salud_filtrado.columns]
            if len(cols_analisis) > 1:
                fig_matrix = px.scatter_matrix(df_salud_filtrado, dimensions=cols_analisis, color="hrv",
                                               title="Matriz de Dependencias (Saturación de color = Recuperación HRV)",
                                               color_continuous_scale="Peach")
                st.plotly_chart(fig_matrix, width='stretch')
else:
    st.warning("⚠️ No se han encontrado archivos CSV locales.")

st.divider()

# ==========================================
# SECCIÓN 2: ENTRENAMIENTOS (.FIT)
# ==========================================
st.header("🚴‍♂️ Rendimiento y Carga de Entrenamiento")

if datos_entrenos:
    df_entrenos = pd.DataFrame(datos_entrenos)
    df_entrenos['distancia_km'] = pd.to_numeric(df_entrenos['distancia_km'], errors='coerce').fillna(0)
    df_entrenos['duracion_min'] = pd.to_numeric(df_entrenos['duracion_min'], errors='coerce').fillna(0)
    df_entrenos['carga_entreno'] = pd.to_numeric(df_entrenos['carga_entreno'], errors='coerce').fillna(0)
    
    if 'fecha_inicio' in df_entrenos.columns:
        df_entrenos['fecha_inicio'] = pd.to_datetime(df_entrenos['fecha_inicio'], errors='coerce')
        df_entrenos = df_entrenos.dropna(subset=['fecha_inicio']).sort_values('fecha_inicio')
        
        fecha_maxima = df_entrenos['fecha_inicio'].max()
        
        # --- MODELO PREDICTIVO TSB ---
        carga_diaria = df_entrenos.set_index('fecha_inicio').resample('D')['carga_entreno'].sum().fillna(0)
        idx_completo = pd.date_range(start=carga_diaria.index.min(), end=fecha_maxima)
        carga_diaria = carga_diaria.reindex(idx_completo, fill_value=0)
        
        if len(carga_diaria) >= 1:
            atl_actual = carga_diaria.rolling(window=7, min_periods=1).mean().iloc[-1]
            ctl_actual = carga_diaria.rolling(window=42, min_periods=1).mean().iloc[-1]
            ratio_carga = atl_actual / ctl_actual if ctl_actual > 0 else 0
            
            st.markdown("### 🔮 Analítica Predictiva de Lesiones (TSB)")
            col_atl, col_ctl, col_riesgo = st.columns(3)
            col_atl.metric("Fatiga Actual (ATL - 7d)", f"{atl_actual:.0f} pts/día")
            col_ctl.metric("Fitness Asimilado (CTL - 42d)", f"{ctl_actual:.0f} pts/día")
            
            if ratio_carga > 1.5:
                col_riesgo.metric("Estado", "⚠️ RIESGO ALTO", "Peligro de lesión", delta_color="inverse")
            elif ratio_carga > 1.2:
                col_riesgo.metric("Estado", "⚡ SOBRECARGA", "Atención a la recuperación")
            elif ratio_carga >= 0.8:
                col_riesgo.metric("Estado", "✅ ÓPTIMO", "Zonas estables")
            else:
                col_riesgo.metric("Estado", "📉 DESENTRENAMIENTO", "Aumenta la carga", delta_color="inverse")
            
            st.divider()

        # --- EVOLUCIÓN DE EFICIENCIA AERÓBICA HISTÓRICA ---
        st.markdown("### 📈 Evolución del Índice de Eficiencia Aeróbica")
        df_running = df_entrenos[df_entrenos['deporte'] == 'running'].copy()
        if not df_running.empty and 'eficiencia_aerobica' in df_running.columns:
            fig_ef = px.scatter(df_running, x='fecha_inicio', y='eficiencia_aerobica', trendline="lowess",
                             title="Eficiencia en Carrera (Metros por minuto / Latido) - ¡Hacia arriba es mejor!",
                             color_discrete_sequence=['#deff9a'])
            st.plotly_chart(fig_ef, width='stretch')

        st.divider()

        # --- FILTRO DE PERIODO (ENTRENOS) ---
        st.markdown("### 📅 Filtro de Entrenamientos")
        opcion_periodo = st.radio("Selecciona el periodo a analizar:", ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"], horizontal=True)
        
        if opcion_periodo == "Últimos 30 días":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=30)
        elif opcion_periodo == "Últimos 3 meses":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=90)
        elif opcion_periodo == "Este Año":
            fecha_filtro = pd.Timestamp(year=fecha_maxima.year, month=1, day=1)
        else:
            fecha_filtro = df_entrenos['fecha_inicio'].min()
            
        df_filtrado = df_entrenos[df_entrenos['fecha_inicio'] >= fecha_filtro]
        
        # --- COMPARATIVA INTERANUAL ---
        inicio_pasado = fecha_filtro - pd.Timedelta(days=365)
        fin_pasado = fecha_maxima - pd.Timedelta(days=365)
        df_pasado = df_entrenos[(df_entrenos['fecha_inicio'] >= inicio_pasado) & (df_entrenos['fecha_inicio'] <= fin_pasado)]
        
        dist_actual = df_filtrado['distancia_km'].sum()
        tiempo_actual_h = df_filtrado['duracion_min'].sum() / 60
        sesiones_actual = len(df_filtrado)
        
        dist_pasada = df_pasado['distancia_km'].sum() if not df_pasado.empty else 0
        tiempo_pasado_h = (df_pasado['duracion_min'].sum() / 60) if not df_pasado.empty else 0
        sesiones_pasada = len(df_pasado) if not df_pasado.empty else 0
        
        st.markdown(f"### 📊 Resumen del Periodo vs Año Pasado")
        c1, c2, c3 = st.columns(3)
        c1.metric("Sesiones", sesiones_actual, f"{sesiones_actual - sesiones_pasada} vs año pasado")
        c2.metric("Distancia Acumulada", f"{dist_actual:.1f} km", f"{dist_actual - dist_pasada:.1f} km")
        c3.metric("Tiempo de Entreno", f"{tiempo_actual_h:.1f} h", f"{tiempo_actual_h - tiempo_pasado_h:.1f} h")
        
        st.divider()
        
        # --- DETALLE DE SESIONES (Modo Compacto sin mapa GPS) ---
        st.markdown(f"### 📝 Detalle de Sesiones ({opcion_periodo})")
        df_filtrado = df_filtrado.sort_values('fecha_inicio', ascending=False)
        
        for _, entreno in df_filtrado.iterrows():
            deporte = str(entreno.get('deporte', '-')).capitalize()
            archivo = entreno.get('nombre_archivo', 'Desconocido')
            distancia = entreno.get('distancia_km', 0)
            fecha_str = entreno['fecha_inicio'].strftime('%d-%m-%Y') if pd.notnull(entreno['fecha_inicio']) else ""
            ef_entreno = entreno.get('eficiencia_aerobica', 0)
            
            txt_ef = f" | EF: {ef_entreno}" if ef_entreno > 0 else ""
            
            with st.expander(f"➔ {fecha_str} | {deporte}: {archivo} ({distancia} km){txt_ef}"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Distancia", f"{distancia} km")
                c2.metric("Duración", f"{entreno.get('duracion_min', 0)} min")
                c3.metric("Ritmo Medio", entreno.get('ritmo', '-:--'))
                c4.metric("Desnivel Positivo", entreno.get('desnivel_positivo', '0 m'))
                
                st.markdown("  ") 
                c5, c6, c7, c8 = st.columns(4)
                c5.metric("FC Media", f"{entreno.get('fc_media', 0)} lpm")
                c6.metric("FC Máxima", f"{entreno.get('fc_max', 0)} lpm")
                c7.metric("Calorías", f"{entreno.get('calorias_kcal', 0)} kcal")
                c8.metric("Carga TRIMP", f"{entreno.get('carga_entreno', 0)} pts")
else:
    st.info("⚠️ Aún no se ha sincronizado el archivo de histórico de entrenamientos.")
    
# ==========================================
# SECCIÓN 3: ENTRENADOR VIRTUAL IA (GEMINI)
# ==========================================
st.divider()
st.header("🤖 AI Coach: Análisis Integral")
st.markdown("Gemini cruzará tus datos y generará dos informes detallados: uno clínico (Salud) y uno deportivo (Rendimiento).")

if st.button("✨ Generar Análisis Completo de mi Estado"):
    with st.spinner("Analizando biomarcadores y carga de entrenamiento..."):
        try:
            from google import genai
            
            client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
            
            p_pasos = f"{media_pasos:,.0f}" if 'media_pasos' in locals() else "Sin datos"
            p_hrv = f"{hrv_medio:.0f} ms" if 'hrv_medio' in locals() else "Sin datos"
            p_sueno = f"{sueno_medio:.1f} h" if 'sueno_medio' in locals() else "Sin datos"
            p_fc = f"{fc_media_global:.0f} lpm" if 'fc_media_global' in locals() else "Sin datos"
            
            p_atl = f"{atl_actual:.0f}" if 'atl_actual' in locals() else "0"
            p_ctl = f"{ctl_actual:.0f}" if 'ctl_actual' in locals() else "0"
            p_ratio = f"{ratio_carga:.2f}" if 'ratio_carga' in locals() else "0"

            prompt = f"""
            Actúa como un médico deportivo y entrenador personal de élite.
            Analiza mis métricas de los últimos 30 días y redacta DOS informes separados pero que se entiendan entre sí.

            DATOS DE SALUD (Promedios diarios):
            - Pasos diarios: {p_pasos}
            - Variabilidad Cardíaca (HRV): {p_hrv}
            - Horas de Sueño: {p_sueno}
            - FC Media: {p_fc}

            DATOS DE ENTRENAMIENTO (Modelo TSB):
            - Carga Aguda (Fatiga actual - ATL): {p_atl}
            - Carga Crónica (Fitness asimilado - CTL): {p_ctl}
            - Ratio de Riesgo de Lesión (ATL/CTL): {p_ratio} (Nota: >1.2 es sobrecarga, >1.5 es riesgo alto).

            ESTRUCTURA TU RESPUESTA EXACTAMENTE ASÍ:

            ### 🩺 1. Análisis de Salud y Recuperación
            (Analiza mi volumen de sueño, variabilidad cardíaca y actividad diaria. ¿Estoy descansando lo suficiente? ¿Mi sistema nervioso muestra signos de estrés crónico o estoy recuperando bien?).

            ### 🚴‍♂️ 2. Análisis de Entrenamiento y Rendimiento
            (Analiza mi carga actual, fitness asimilado y riesgo de lesión. Cruza esta información obligatoriamente con mi estado de recuperación de la sección anterior para decirme exactamente qué enfoque o intensidad de sesión debo hacer hoy).
            
            Usa un tono motivador, directo y científico.
            """
            
            respuesta = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            
            st.success("✅ Análisis completado con éxito.")
            st.info(respuesta.text)
            
        except Exception as e:
            st.error(f"Error al conectar con la IA: {e}")
            st.markdown("⚠️ Comprueba que has añadido `GEMINI_API_KEY` a los secretos (Secrets) de Streamlit.")