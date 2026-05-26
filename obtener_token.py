import dropbox

APP_KEY = '75rli9slf739oju'
APP_SECRET = 'ig6djx2vcc8nn6w'

auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(APP_KEY, APP_SECRET, token_access_type='offline')
authorize_url = auth_flow.start()

print("1. Abre esta URL en tu navegador web:")
print(authorize_url)
print("---")
print("2. Haz clic en 'Allow' (Permitir) y aparecerá un código en la pantalla.")

auth_code = input("3. Pega ese código aquí y pulsa Enter: ").strip()

try:
    oauth_result = auth_flow.finish(auth_code)
    print("\n✅ ¡ÉXITO! Guarda este token como oro en paño:")
    print("REFRESH_TOKEN =", oauth_result.refresh_token)
except Exception as e:
    print('Error:', e)