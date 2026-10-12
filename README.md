mvppy

Requisitos
Python 3.13.x
Microsoft Visual C++ Redistributable (x64), caso exigido pelas dependências utilizadas.
Git, para clonar o repositório.
Bibliotecas principais
OpenCV (opencv-python): processamento de imagens e vídeos.
PyYAML (PyYAML): leitura e escrita de arquivos YAML.
Ultralytics (ultralytics): utilização de modelos de visão computacional, como YOLO.

As dependências adicionais dessas bibliotecas são instaladas automaticamente pelo pip.

Instalação
1. Clone o repositório
git clone <URL_DO_REPOSITORIO>
cd mvppy

2. Crie o ambiente virtual
py -3.13 -m venv venv

3. Ative o ambiente virtual
.\venv\Scripts\Activate.ps1

4. Atualize o pip
python -m pip install --upgrade pip

5. Instale as dependências
python -m pip install -r requirements.txt

6. Verifique as instalações
python -c "import cv2, yaml; from ultralytics import YOLO; print('Dependências carregadas com sucesso!')"

Observações
O Microsoft Visual C++ Redistributable é um componente externo ao Python e não é instalado pelo requirements.txt. Se necessário, instale-o pelo site oficial da Microsoft.
O uso de GPU NVIDIA pode exigir uma configuração adicional do PyTorch e dos componentes CUDA compatíveis.
Consulte as instruções específicas do projeto antes de executá-lo.