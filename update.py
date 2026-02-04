import os
import xbmc
import xbmcaddon
import xbmcgui
import urllib.request
import zipfile
import shutil
import xbmcvfs  # Importar a biblioteca correta

# Configuração do repositório
GITHUB_API_URL = "https://api.github.com/repos/JorgeBeserra/CarPc-Carbon-K19/releases/latest"
GITHUB_DOWNLOAD_URL = "https://github.com/JorgeBeserra/CarPc-Carbon-K19/releases/latest/download/update.zip"
ADDON_PATH = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('path'))
CURRENT_VERSION = xbmcaddon.Addon().getAddonInfo('version')

def download_update():
    zip_path = os.path.join(ADDON_PATH, "update.zip")

    try:
        xbmcgui.Dialog().notification("Atualizador", "Baixando atualização...", xbmcgui.NOTIFICATION_INFO, 3000)
        urllib.request.urlretrieve(GITHUB_DOWNLOAD_URL, zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(ADDON_PATH)

        os.remove(zip_path)

        xbmcgui.Dialog().notification("Atualizador", "Atualização concluída!", xbmcgui.NOTIFICATION_INFO, 5000)
        xbmc.executebuiltin("RestartApp()")  # Reinicia o Kodi para aplicar a atualização

    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha ao atualizar: {str(e)}", xbmcgui.NOTIFICATION_ERROR, 5000)

def compare_versions(current_version, latest_version):
    """Compara duas versões no formato X.Y.Z e retorna True se a mais recente for maior."""
    current = [int(x) for x in current_version.split('.')]
    latest = [int(x) for x in latest_version.split('.')]
    return latest > current

def check_for_update():
    try:
        # Consulta a API do GitHub para obter a versão mais recente
        xbmc.log("Verificando versão mais recente no GitHub", xbmc.LOGINFO)
        with urllib.request.urlopen(GITHUB_API_URL) as response:
            release_info = json.loads(response.read().decode('utf-8'))
            latest_version = release_info['tag_name'].lstrip('v')  # Ex.: "2.0.12" (remove 'v' se presente)
        
        xbmc.log(f"Versão atual: {CURRENT_VERSION}, Versão mais recente: {latest_version}", xbmc.LOGINFO)
        
        # Compara as versões
        if compare_versions(CURRENT_VERSION, latest_version):
            xbmc.log("Nova versão disponível, iniciando download", xbmc.LOGINFO)
            download_update()
        else:
            xbmc.log("Nenhuma nova versão disponível", xbmc.LOGINFO)
            xbmcgui.Dialog().notification("Atualizador", "Você já está na versão mais recente!", xbmcgui.NOTIFICATION_INFO, 3000)
    except Exception as e:
        xbmc.log(f"Erro ao verificar atualização: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Erro", f"Falha ao verificar atualização: {str(e)}", xbmcgui.NOTIFICATION_ERROR, 5000)

if __name__ == "__main__":
    check_for_update()
