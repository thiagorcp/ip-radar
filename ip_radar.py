import os
import json
import ipaddress
import PySimpleGUI as sg
import subprocess
import threading
import time
from datetime import datetime
import platform

# ==========================
#   CONFIGURAÇÃO DE DIRETÓRIOS
# ==========================
if platform.system() == "Windows":
    BASE_DIR = r"C:/ip_radar"
else:
    BASE_DIR = os.path.join(os.path.expanduser("~"), "ip_radar")

HOSTS_DIR = os.path.join(BASE_DIR, "hosts")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
HOSTS_JSON = os.path.join(HOSTS_DIR, "hosts.json")


# ==========================
#   FUNÇÕES AUXILIARES
# ==========================
def inicializar_diretorios():
    """Cria os diretórios se não existirem."""
    os.makedirs(HOSTS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


def carregar_hosts():
    """
    Carrega o arquivo JSON de hosts.
    Se não existir, cria e retorna uma lista vazia.
    Cada host terá as chaves: "nome", "ip" e "status".
    """
    if not os.path.isfile(HOSTS_JSON):
        with open(HOSTS_JSON, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=4)
        return []
    else:
        with open(HOSTS_JSON, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                for host in data:
                    if "status" not in host:
                        host["status"] = "Aguardando"
                return data
            except json.JSONDecodeError:
                return []


def salvar_hosts(lista_hosts):
    """Salva a lista de hosts no arquivo JSON."""
    with open(HOSTS_JSON, 'w', encoding='utf-8') as f:
        json.dump(lista_hosts, f, indent=4, ensure_ascii=False)


def registrar_log(mensagem):
    """
    Registra a mensagem no arquivo de log.
    O arquivo tem o formato "log_YYYYMMDD.txt".
    """
    data_atual = datetime.now().strftime("%Y%m%d")
    arquivo_log = os.path.join(LOGS_DIR, f"log_{data_atual}.txt")
    with open(arquivo_log, 'a', encoding='utf-8') as f:
        f.write(mensagem + "\n")


def ping_host(ip):
    """
    Envia um ping para o IP informado.
    Retorna True se houver resposta, False caso contrário.
    Os parâmetros do comando de ping variam conforme o sistema.
    """
    try:
        sistema = platform.system()
        if sistema == "Windows":
            args = ["ping", "-n", "1", "-w", "1000", ip]
        else:
            args = ["ping", "-c", "1", "-W", "1", ip]

        result = subprocess.run(args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True)
        if "TTL=" in result.stdout.upper() or "ttl=" in result.stdout.lower():
            return True
        else:
            return False
    except Exception as e:
        print(f"Erro ao executar ping em {ip}: {e}")
        return False


def validar_ip(ip_str):
    """
    Verifica se ip_str é um endereço IP válido.
    Retorna True se for válido, False caso contrário.
    """
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def editar_hosts_window(lista_hosts):
    """
    Abre uma janela para exibir e editar os hosts cadastrados.
    Permite ao usuário selecionar um host, modificar os campos e
    salvar as alterações. A função retorna a lista atualizada.
    """
    data_table = [[host["nome"], host["ip"]] for host in lista_hosts]
    layout = [
        [sg.Text("Clique na linha para editar o host selecionado.")],
        [sg.Table(values=data_table,
                  headings=["Nome", "IP"],
                  key="-TABLE_EDIT-",
                  enable_events=True,
                  num_rows=10,
                  auto_size_columns=True,
                  justification="left",
                  select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Text("Nome:"), sg.Input(key="-EDIT_NOME-", size=(20, 1))],
        [sg.Text("IP:"), sg.Input(key="-EDIT_IP-", size=(20, 1))],
        [sg.Button("Atualizar", key="-ATUALIZAR-"), sg.Button("Fechar")]
    ]
    win_edit = sg.Window("Editar Hosts", layout, modal=True)
    host_index = None

    while True:
        event, values = win_edit.read()
        if event in (sg.WIN_CLOSED, "Fechar"):
            break

        if event == "-TABLE_EDIT-":
            try:
                host_index = values["-TABLE_EDIT-"][0]
                host = lista_hosts[host_index]
                win_edit["-EDIT_NOME-"].update(host["nome"])
                win_edit["-EDIT_IP-"].update(host["ip"])
            except IndexError:
                pass

        elif event == "-ATUALIZAR-":
            if host_index is None:
                sg.popup("Selecione um host para editar!")
                continue

            novo_nome = values["-EDIT_NOME-"].strip()
            novo_ip = values["-EDIT_IP-"].strip()
            if not novo_nome:
                sg.popup("O nome não pode ficar vazio!")
                continue
            if not validar_ip(novo_ip):
                sg.popup("Entrada inválida para IP!")
                continue

            lista_hosts[host_index]["nome"] = novo_nome
            lista_hosts[host_index]["ip"] = novo_ip
            data_table = [[host["nome"], host["ip"]] for host in lista_hosts]
            win_edit["-TABLE_EDIT-"].update(values=data_table)
            salvar_hosts(lista_hosts)
            sg.popup("Host atualizado com sucesso!")
    win_edit.close()
    return lista_hosts


# ==========================
#   CLASSE DE MONITORAMENTO
# ==========================
class MonitoramentoHosts:
    """
    Gerencia o envio de pacotes ICMP em uma thread separada e envia
    eventos para atualizar a interface.
    """

    def __init__(self, hosts, window, interval=60):
        self.hosts = hosts
        self.window = window
        self.interval = interval  # intervalo total em segundos para cada rodada
        self.running = False
        self.thread = None

    def start(self):
        if not self.running:
            self.running = True
            hora_inicio = datetime.now().strftime("%H:%M:%S")
            msg_inicio = f"Monitoramento Iniciado às {hora_inicio}"
            registrar_log(msg_inicio)
            self.window.write_event_value("-LOG_UPDATE-", msg_inicio)
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        hora_pausa = datetime.now().strftime("%H:%M:%S")
        msg_pausa = f"Monitoramento Pausado às {hora_pausa}"
        registrar_log(msg_pausa)
        self.window.write_event_value("-LOG_UPDATE-", msg_pausa)
        if self.thread is not None:
            self.thread.join(timeout=2)

    def run(self):
        while self.running:
            # Envio dos pings para os hosts cadastrados
            for i, host in enumerate(self.hosts):
                if not self.running:
                    break
                nome = host["nome"]
                ip = host["ip"]
                hora_atual = datetime.now().strftime("%H:%M:%S")
                mensagem_envio = f"Pacote ICMP Enviado para {nome} - {ip} às {hora_atual}"
                registrar_log(mensagem_envio)
                self.window.write_event_value("-LOG_UPDATE-", mensagem_envio)

                status_online = ping_host(ip)
                hora_atual = datetime.now().strftime("%H:%M:%S")
                if status_online:
                    mensagem_recebida = f"Pacote ICMP Recebido de {nome} - {ip} às {hora_atual}"
                    registrar_log(mensagem_recebida)
                    host["status"] = "Online"
                    self.window.write_event_value("-LOG_UPDATE-", mensagem_recebida)
                else:
                    host["status"] = "Offline"

                nova_tabela = [[h["nome"], h["ip"], h.get("status", "Aguardando")] for h in self.hosts]
                self.window.write_event_value("-TABLE_UPDATE-", nova_tabela)

                # Pausa curta entre pings individuais
                for _ in range(5):
                    if not self.running:
                        break
                    time.sleep(0.1)

            # Ao final do ciclo, se ainda rodando, exibe mensagem de nova transmissão (sem alterar a animação)
            if self.running:
                self.window.write_event_value("-LOG_UPDATE-", "Nova transmissão Iniciada em 1 minuto")
                registrar_log("Nova transmissão Iniciada em 1 minuto")

            # Durante o intervalo, exibe somente os pontos acumulados
            wait_time = 0
            animation = ""
            while self.running and wait_time < self.interval:
                time.sleep(1)
                wait_time += 1
                animation += "#"
                self.window.write_event_value("-ANIM_UPDATE-", animation)


# ==========================
#   FUNÇÃO PRINCIPAL (GUI)
# ==========================
def main():
    sg.theme("DarkBlue4")
    inicializar_diretorios()

    lista_hosts = carregar_hosts()

    col_hosts = [
        [sg.Text("Hosts Monitorados:", font=("Helvetica", 12, "bold"))],
        [sg.Table(values=[[h["nome"], h["ip"], h.get("status", "Aguardando")] for h in lista_hosts],
                  headings=["Host", "IP", "Status"],
                  col_widths=[20, 15, 10],
                  auto_size_columns=False,
                  justification="left",
                  key="-HOSTS_TABLE-",
                  select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                  num_rows=6)],
        [sg.Text("Nome do Host:"), sg.Input(key="-NOME-", size=(20, 1))],
        [sg.Text("IP do Host:"), sg.Input(key="-IP-", size=(20, 1))],
        [sg.Button("Adicionar IP do Host", key="-ADD-")],
        [sg.Button("Iniciar Monitoramento", key="-START-", button_color=("white", "green")),
         sg.Button("Parar Monitoramento", key="-STOP-", button_color=("white", "red"))],
        [sg.Button("Editar Hosts", key="-EDIT-"),
         sg.Button("Salvar Log", key="-SAVE_LOG-")]
    ]

    # Adicionamos um elemento de texto para exibir a animação dos pontos
    col_log = [
        [sg.Text("Log de eventos:")],
        [sg.Multiline(size=(60, 15), key="-LOG-", autoscroll=True, disabled=True)],
        [sg.Text("", key="-ANIM-", size=(60, 1))]
    ]

    layout = [
        [sg.Column(col_hosts), sg.VSeparator(), sg.Column(col_log)]
    ]

    window = sg.Window("IP Radar", layout, finalize=True)

    monitor = MonitoramentoHosts(lista_hosts, window, interval=60)

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            monitor.stop()
            break

        elif event == "-ADD-":
            nome = values["-NOME-"].strip()
            ip = values["-IP-"].strip()
            if not nome:
                sg.popup("O campo Nome do Host não pode ficar vazio!")
                continue
            if not validar_ip(ip):
                sg.popup("Entrada inválida para IP do Host!")
                continue
            novo_host = {"nome": nome, "ip": ip, "status": "Aguardando"}
            lista_hosts.append(novo_host)
            salvar_hosts(lista_hosts)
            window["-HOSTS_TABLE-"].update([[h["nome"], h["ip"], h.get("status", "Aguardando")] for h in lista_hosts])
            window["-NOME-"].update("")
            window["-IP-"].update("")

        elif event == "-START-":
            monitor.hosts = lista_hosts  # Atualiza a lista caso haja novos hosts
            monitor.start()

        elif event == "-STOP-":
            monitor.stop()

        elif event == "-EDIT-":
            lista_hosts = editar_hosts_window(lista_hosts)
            salvar_hosts(lista_hosts)
            window["-HOSTS_TABLE-"].update([[h["nome"], h["ip"], h.get("status", "Aguardando")] for h in lista_hosts])

        elif event == "-SAVE_LOG-":
            sg.popup("Os logs são salvos automaticamente em " + LOGS_DIR)

        elif event == "-LOG_UPDATE-":
            mensagem = values["-LOG_UPDATE-"]
            # Acrescenta a mensagem no log (cada evento vem em nova linha)
            window["-LOG-"].print(mensagem)

        elif event == "-TABLE_UPDATE-":
            nova_tabela = values["-TABLE_UPDATE-"]
            window["-HOSTS_TABLE-"].update(values=nova_tabela)

        elif event == "-ANIM_UPDATE-":
            # Atualiza o elemento de animação com os pontos acumulados
            window["-ANIM-"].update(value=values["-ANIM_UPDATE-"])

    window.close()


if __name__ == "__main__":
    main()
