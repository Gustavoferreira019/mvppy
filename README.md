# VIGIL.AI — Alpha 0.2.0

VIGIL.AI é um protótipo de vigilância inteligente para executar localmente, receber vídeo de câmeras, detectar pessoas e objetos configurados em uma zona definida e salvar um clipe do evento. Esta documentação descreve o estado da versão Alpha para desenvolvedores e para quem precisa preparar uma instalação de teste.

## O que existe nesta versão

- Captura de webcam/USB, câmera de rede por RTSP e fontes compatíveis com ONVIF.
- Cadastro de várias câmeras e canais no mesmo arquivo de configuração.
- Vínculo exclusivo de uma fonte: depois que uma webcam, câmera IP, NVR ou canal é cadastrado, ela fica reservada até o cadastro ser excluído.
- Painel local para cadastrar, editar, testar e excluir fontes, com indicação do estado de cada fonte.
- Descoberta de dispositivos ONVIF na rede local quando o equipamento anuncia esse protocolo.
- Configuração visual da zona monitorada em coordenadas normalizadas de 0 a 1.
- Detecção configurável de pessoas e objetos comuns do modelo COCO com YOLOv8, gerando eventos quando uma detecção entra na zona.
- Buffer anterior e gravação posterior ao evento, com vídeo MP4 e metadados JSON.
- Recarga da configuração em runtime: alterações salvas no painel são percebidas pelo processo de monitoramento sem reiniciar o serviço.
- Prévia no painel, estado offline e aviso quando a fonte está sendo utilizada pelo monitoramento.

## Limites importantes do Alpha

O Alpha reconhece classes genéricas do modelo COCO, mas não conclui sozinho que houve furto, identifica marcas/SKUs ou substitui uma análise humana. Latas e mercadorias específicas exigem um modelo treinado para o ambiente do cliente. A inferência é local, as credenciais ficam no YAML em texto simples e o envio para Telegram/nuvem, autenticação de usuários, instalador Windows e execução como serviço ainda não fazem parte desta versão.

## Arquitetura

| Componente | Responsabilidade |
| --- | --- |
| `app.py` | Processo de monitoramento, captura, inferência, eventos, gravação e atualização de `runtime_status.json`. |
| `setup_server.py` | Painel HTTP local em `http://127.0.0.1:8765` para configurar as fontes. |
| `capture/capture.py` | Captura em thread e reconexão de fontes. |
| `detector/detector.py` | Carregamento do modelo, filtro de classes e detecção/rastreamento. |
| `events/engine.py` | Regra de entrada na zona e cooldown entre eventos. |
| `recording/recorder.py` | Buffer circular, MP4 e JSON do evento. |
| `ui/renderer.py` | Renderização da grade de câmeras e sobreposição da zona. |
| `onvif_client.py` / `onvif_discovery.py` | Descoberta ONVIF e obtenção do perfil de vídeo. |
| `launcher.py` | Orquestração do pacote executável: inicia o núcleo, o configurador e abre o navegador. |
| `config/config.yaml` | Configuração persistida das câmeras e parâmetros do sistema. |

## Requisitos de desenvolvimento

- Windows 10/11 (o fluxo atual usa OpenCV e captura DirectShow/Media Foundation).
- Python 3.10 ou superior; o ambiente usado para o Alpha é Python 3.13.
- Uma câmera local, uma URL RTSP ou um dispositivo ONVIF para testar.
- O arquivo `yolov8n.pt` na raiz, ou outro modelo compatível configurado em `detector.model_path`.
- CPU funciona para testes. Uma GPU compatível com PyTorch melhora o desempenho quando há várias câmeras.

## Instalação para desenvolver

No PowerShell, na raiz do projeto:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se a política do PowerShell impedir a ativação, execute os comandos usando diretamente `venv\Scripts\python.exe`.

## Executar a versão fonte

Em dois terminais, com o ambiente virtual ativo:

```powershell
python app.py
```

```powershell
python setup_server.py
```

Depois abra `http://127.0.0.1:8765`. O painel precisa estar ativo para configurar fontes; o monitoramento continua no `app.py`. Para encerrar, volte aos terminais e pressione `Ctrl+C`.

Também existe o `launcher.py`, que inicia os dois processos quando os executáveis internos do pacote estão presentes. Rodar `python launcher.py` diretamente só é útil durante a preparação do pacote; para uso do cliente, utilize o executável empacotado descrito abaixo.

## Simulador ONVIF para desenvolvimento

Para testar a descoberta ONVIF sem uma câmera física, execute o simulador em um terceiro terminal, na raiz do projeto:

```powershell
venv\Scripts\python.exe scripts\simulate_onvif_camera.py
```

Ele anuncia uma câmera de teste por WS-Discovery na rede local e fornece um stream MJPEG em `http://127.0.0.1:8890/video.mjpg`. A imagem é sintética, com o nome do dispositivo e um relógio, para confirmar que a prévia está realmente recebendo quadros. Qualquer usuário e senha são aceitos pelo simulador.

No painel, siga o fluxo normal: selecione **Câmera ONVIF**, clique em **Buscar câmeras ONVIF**, escolha **VIGIL.AI Câmera de Teste**, informe usuário e senha e clique em **Testar conexão**. O dispositivo deve aparecer na lista, o perfil **Principal** deve ser obtido e a prévia/zona deve ser liberada. Depois, ele pode ser cadastrado e editado como qualquer câmera real.

Pressione `Ctrl+C` no terminal do simulador para removê-lo da rede. O script é uma ferramenta de desenvolvimento e não é copiado para o ZIP do cliente. Se o Windows Firewall bloquear descoberta multicast, permita o Python na rede privada ou execute o painel e o simulador na mesma rede/perfil; o protocolo WS-Discovery usa UDP 3702.

## Executar o pacote Alpha

O artefato da próxima entrega é `dist/VigilAI-alpha-0.2.0.zip`. Extraia o ZIP em uma pasta com permissão de escrita e execute `VigilAI-alpha-0.2.0.exe`. O launcher inicia o núcleo e o configurador, abre o navegador local e encerra o configurador quando o núcleo termina.

A pasta extraída precisa permanecer inteira: o executável depende de `core/`, `configurator/`, `config/`, do modelo e dos arquivos de runtime. O YAML e os clipes ficam na pasta do pacote, para que a instalação seja portátil e possa ser copiada para outro computador.

## Fluxo do painel

1. Abra o painel e escolha uma seção: **Adicionar câmera**, **Câmeras cadastradas** ou **Editar câmera**.
2. Em **Adicionar câmera**, escolha o tipo de fonte.
3. Preencha o nome da câmera. O nome é obrigatório antes de testar ou salvar.
4. Preencha somente os campos exibidos para aquela fonte.
5. Clique em **Testar conexão**. O painel valida os campos obrigatórios e só libera a prévia/zona quando a fonte responde.
6. Desenhe a área monitorada sobre a prévia ou ajuste os quatro valores da zona.
7. Ajuste os segundos antes/depois e clique em **Salvar configuração**.
8. O cadastro passa a aparecer em **Câmeras cadastradas**. Clique no cartão para editar ou excluir.

Ao mudar o tipo de fonte, a seleção anterior, a prévia, a zona e o estado do teste são limpos. Uma fonte já vinculada não pode ser testada ou cadastrada novamente; primeiro exclua o cadastro que a utiliza. Durante a edição, a fonte vinculada é mostrada em modo somente leitura. Isso vale para webcam, câmera IP, ONVIF, câmera manual e NVR/canal.

### Tipos de fonte

**Webcam do notebook/USB** — selecione uma webcam detectada pelo computador. O valor exibido como `Webcam 0` corresponde ao índice usado pelo OpenCV. O mesmo índice fica reservado ao cadastro até a câmera ser excluída.

**Câmera ONVIF (Wi-Fi ou rede)** — clique em **Buscar câmeras ONVIF** e selecione o dispositivo encontrado. O endereço é preenchido automaticamente e fica somente leitura; informe apenas usuário e senha. O VIGIL.AI obtém o URI de vídeo quando o equipamento fornece essa informação; o usuário não precisa montar o caminho RTSP.

**Câmera de rede (RTSP manual)** — informe host/IP, credenciais, fabricante, canal, stream, protocolo e porta. O campo de caminho RTSP é preenchido pelo sistema a partir desses dados e fica somente leitura. Use esta opção quando a câmera/NVR não responder à descoberta ONVIF.

Para um NVR com várias câmeras, cada canal que será monitorado deve ter um cadastro próprio (por exemplo, `NVR Entrada`, `NVR Caixa` e `NVR Estoque`). Isso permite uma zona e um estado independente por canal. Canais sem cadastro não entram no processamento.

## Zona, eventos e clipes

A zona é armazenada como `[x1, y1, x2, y2]`, com todos os valores entre `0` e `1`. `0,0` é o canto superior esquerdo e `1,1` é o canto inferior direito. O painel converte o desenho para essa escala, então a zona continua válida mesmo quando a resolução muda.

Quando o centro da caixa de uma detecção configurada entra na zona, o motor cria um evento como `person_in_restricted_zone` ou `handbag_in_restricted_zone`. O JSON inclui a classe, o ID rastreado e a confiança. O cooldown evita repetir o mesmo alerta continuamente. O gravador mantém os últimos `recording.before_seconds` de vídeo e continua por `recording.after_seconds` depois do evento.

Por padrão, os arquivos são gravados em `events/clips/`:

- `event_YYYYMMDD_HHMMSS_microssegundos.mp4`: clipe do evento.
- `event_YYYYMMDD_HHMMSS_microssegundos.json`: tipo, confiança, zona, horário e caminhos dos arquivos.

## Configuração YAML

Um exemplo mínimo:

```yaml
capture:
  cameras:
    - id: entrada
      name: Entrada
      source: 0
      zone: [0.10, 0.10, 0.82, 0.82]
      enabled: true

detector:
  model_path: yolov8n.pt
  confidence: 0.5
  classes: [person, car, dog, cat, bird, backpack, handbag, suitcase, bottle, cup, laptop, cell phone]

performance:
  inference_fps: 5
  display_fps: 20
  display_size: [640, 360]
  camera_timeout_seconds: 5

events:
  cooldown_seconds: 10

recording:
  output_dir: events/clips
  fps: 20
  before_seconds: 10
  after_seconds: 5
```

Prefira alterar o YAML pelo painel. A lista `detector.classes` define as classes analisadas; use os nomes do modelo COCO em inglês ou deixe a lista vazia para analisar todas as classes disponíveis. Se for necessário editar manualmente, mantenha `source`, `id`, `zone` e `enabled` válidos. O `app.py` recarrega o arquivo quando seu conteúdo muda e atualiza as câmeras e classes em runtime.

## Estado e diagnóstico

`runtime_status.json` é escrito pelo monitoramento para indicar câmeras ativas, erros e última atualização. Ele é um artefato local e não deve ser versionado. Uma tela preta com `Câmera/NVR sendo utilizada` significa que a fonte está ocupada pelo `app.py`; `OFFLINE` significa que a fonte não respondeu. Para rede, o painel oferece nova tentativa automática/manual.

Mensagens comuns:

- **Porta 8765 ocupada:** encerre outro `setup_server.py` ou altere a porta no código antes de iniciar.
- **Fonte já vinculada:** edite o cadastro existente ou exclua-o antes de reutilizar o dispositivo.
- **Webcam indisponível / `Camera index out of range`:** outro programa está usando a webcam, o índice não existe ou o driver não entregou quadros.
- **Modelo não encontrado:** confira `detector.model_path` e mantenha o `.pt` na raiz do pacote.
- **RTSP/ONVIF offline:** valide IP, porta, credenciais, rede e se o equipamento permite RTSP/ONVIF.
- **Desempenho baixo:** reduza `display_size` e `inference_fps`, use o stream secundário e evite abrir uma janela de vídeo por processo.

## Verificações antes de um commit

```powershell
python -m py_compile app.py setup_server.py launcher.py capture\capture.py detector\detector.py events\engine.py recording\recorder.py ui\renderer.py onvif_client.py onvif_discovery.py
git status --short
```

Não inclua ambiente virtual, clipes, estados de execução, caches, builds ou credenciais no commit. O `.gitignore` do projeto já cobre esses artefatos. Se um cliente fornecer uma configuração real, remova usuários, senhas, IPs públicos e URLs privadas antes de compartilhá-la.

## Build para distribuição

O build depende do PyInstaller e das dependências instaladas no ambiente virtual. Os arquivos `.spec`, `build/`, `dist/` e `.release-work/` são saídas locais e estão ignorados no Git. Gere uma build somente quando houver uma versão para entregar:

```powershell
.\scripts\build-release.ps1 --name alpha-0.2.0
```

`--name` é obrigatório e recebe o identificador da versão. Por exemplo, `--name alpha-0.2.0` gera `dist/VigilAI-alpha-0.2.0.zip`, contendo o launcher `VigilAI-alpha-0.2.0.exe`. Se o parâmetro for omitido, o script encerra sem iniciar a build.

O script mostra uma barra de progresso por etapas: geração do launcher, configurador, núcleo, cópia dos arquivos e compactação. O percentual é uma estimativa baseada nas fases informadas pelo PyInstaller; ele serve para acompanhar o andamento, enquanto o processo continua podendo demorar por causa do PyTorch, torchvision, OpenCV, YOLO e do modelo incluído.

Valide o ZIP em uma máquina limpa antes de enviá-lo ao sócio ou a um cliente. O manual `LEIA-ME.txt` é incluído dentro do pacote com o nome da build atualizado.

## Próximos passos fora do Alpha

Inferência em serviço/cloud, envio de eventos ao Telegram, autenticação, criptografia de credenciais, atualização automática, execução como serviço do Windows, suporte robusto a múltiplos canais de NVR e regras específicas de furto devem ser planejados antes de uma versão Beta comercial.
