import os
import re
from datetime import datetime, time
import httpx
from typing import Optional
import pytz

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
import uvicorn

# --- CONFIGURAÇÃO DE TIMEZONE (MANAUS/AMAZONAS) ---
tz_am = pytz.timezone('America/Manaus')

# --- CONFIGURAÇÃO DO BANCO DE DADOS (SQLite) ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./sentinela_mulher.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MedidaProtetiva(Base):
    __tablename__ = "medidas_protetivas"
    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(String, unique=True, index=True)
    nome_vitima = Column(String)
    telefone_vitima = Column(String)
    distancia_minima = Column(Float, default=500.0)
    foto_agressor_url = Column(String, nullable=True)
    data_validade = Column(String)

class HistoricoViolacao(Base):
    __tablename__ = "historico_violacoes"
    id = Column(Integer, primary_key=True, index=True)
    medida_id = Column(Integer, ForeignKey("medidas_protetivas.id"))
    timestamp = Column(DateTime, default=lambda: datetime.now(tz_am))
    distancia_detectada = Column(Float)
    lat_agressor = Column(Float)
    long_agressor = Column(Float)
    status_notificacao = Column(String)
    medida_vigente_na_hora = Column(String)

Base.metadata.create_all(bind=engine)

# --- SEGURANÇA OAUTH2 ---
app = FastAPI(title="Sentinela Mulher - Amazonas", version="2.6.0")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Credenciais padrão para a Polícia/Segurança
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial_2026", "token_type": "bearer"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial_2026":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return token

# --- VALIDADORES TÉCNICOS ---

def limpar_e_validar_telefone(tel_bruto: str) -> str:
    """Remove caracteres especiais e valida se há DDD + 9 dígitos."""
    numeros = re.sub(r"\D", "", tel_bruto)
    if len(numeros) != 11:
        raise HTTPException(
            status_code=400, 
            detail="Telefone inválido. Formato exigido: (DDD) 9XXXX-XXXX (11 dígitos)."
        )
    return numeros

def verificar_vigencia(data_str: str) -> bool:
    """Converte padrão brasileiro e compara com o horário de Manaus."""
    if not data_str: return False
    try:
        data_limpa = data_str.strip().replace("-", "/")
        agora = datetime.now(tz_am)
        data_exp = datetime.strptime(data_limpa, "%d/%m/%Y")
        # Válido até o último segundo do dia informado
        data_exp_final = tz_am.localize(datetime.combine(data_exp.date(), time(23, 59, 59)))
        return agora <= data_exp_final
    except:
        return False

# --- WEBHOOK (COLE SEU LINK AQUI) ---
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

# --- ENDPOINTS OPERACIONAIS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(..., example="0012345-67.2026.8.04.0001"), 
    vitima: str = Body(..., example="Maria da Silva"), 
    telefone: str = Body(..., example="(92) 98888-7777"),
    validade: str = Body(..., example="31/12/2026"), 
    raio: float = Body(500.0), 
    foto: str = Body(None),
    db: Session = Depends(get_db), 
    token: str = Depends(verificar_token)
):
    tel_limpo = limpar_e_validar_telefone(telefone)
    
    nova = MedidaProtetiva(
        processo_id=processo.strip(), 
        nome_vitima=vitima, 
        telefone_vitima=tel_limpo,
        distancia_minima=raio, 
        foto_agressor_url=foto, 
        data_validade=validade
    )
    db.add(nova)
    db.commit()
    return {"status": "Processo registrado com sucesso", "telefone_sanitizado": tel_limpo}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(..., description="Número do processo cadastrado"), 
    ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db), 
    token: str = Depends(verificar_token)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso.strip()).first()
    if not medida:
        raise HTTPException(status_code=404, detail="Processo não localizado no sistema.")

    vigente = verificar_vigencia(medida.data_validade)
    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    notif = "N/A"
    
    if dist <= medida.distancia_minima:
        maps = f"https://www.google.com/maps?q={ag_lat},{ag_long}"
        
        # Envio de Alerta Crítico ao Webhook
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                await client.post(WEBHOOK_URL, json={
                    "evento": "VIOLAÇÃO DE PERÍMETRO",
                    "vitima": medida.nome_vitima,
                    "status_juridico": "VIGENTE" if vigente else "EXPIRADA",
                    "distancia": f"{round(dist, 2)}m",
                    "contato": medida.telefone_vitima,
                    "mapa": maps,
                    "foto": medida.foto_agressor_url
                })
                notif = "Alerta Enviado"
            except:
                notif = "Falha de Comunicação"
        
        # Log de Violação
        log = HistoricoViolacao(
            medida_id=medida.id, 
            distancia_detectada=round(dist, 2),
            lat_agressor=ag_lat, 
            long_agressor=ag_long, 
            status_notificacao=notif, 
            medida_vigente_na_hora="SIM" if vigente else "NÃO"
        )
        db.add(log)
        db.commit()

    return {
        "resultado": "🚨 VIOLAÇÃO" if dist <= medida.distancia_minima else "OK",
        "vigencia": "ATIVA" if vigente else "EXPIRADA",
        "distancia_atual": f"{round(dist, 2)}m",
        "vitima": medida.nome_vitima
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_oficial(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id.strip()).first()
    if not medida:
        return "<h1>Erro: Processo não encontrado.</h1>"
    
    vigente = verificar_vigencia(medida.data_validade)
    cor_status = "#28a745" if vigente else "#dc3545"
    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    
    # Formatação do telefone: (92) 98888-7777
    t = medida.telefone_vitima
    tel_fmt = f"({t[:2]}) {t[2:7]}-{t[7:]}"

    linhas = ""
    for v in violacoes:
        v_cor = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{v.lat_agressor}, {v.long_agressor}</td><td style='color:{v_cor}; font-weight:bold;'>{v.medida_vigente_na_hora}</td></tr>"

    return f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: sans-serif; padding: 40px; color: #333; }}
            .header {{ text-align: center; border-bottom: 5px solid #003366; padding-bottom: 15px; }}
            .status {{ background: {cor_status}; color: white; padding: 10px 25px; border-radius: 25px; display: inline-block; font-weight: bold; margin-top: 15px; }}
            .card {{ display: flex; border: 1px solid #ddd; margin-top: 25px; background: #f9f9f9; padding: 20px; border-radius: 8px; }}
            .foto {{ width: 160px; height: 200px; border: 4px solid #003366; object-fit: cover; border-radius: 4px; }}
            .info {{ margin-left: 30px; line-height: 1.6; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background: #003366; color: white; }}
            @media print {{ .no-print {{ display: none; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin:0; color:#003366;">SISTEMA SENTINELA MULHER</h1>
            <p style="margin:5px;">Secretaria de Segurança Pública do Amazonas</p>
            <div class="status">STATUS DA MEDIDA: {'VIGENTE' if vigente else 'EXPIRADA'}</div>
        </div>

        <div class="card">
            <img src="{medida.foto_agressor_url or 'https://via.placeholder.com/160x200?text=SEM+FOTO'}" class="foto">
            <div class="info">
                <p><b>Nº PROCESSO:</b> {medida.processo_id}</p>
                <p><b>VÍTIMA:</b> {medida.nome_vitima}</p>
                <p><b>CONTATO:</b> {tel_fmt}</p>
                <p><b>VALIDADE JURÍDICA:</b> {medida.data_validade}</p>
                <p><b>RAIO DE MONITORAMENTO:</b> {medida.distancia_minima}m</p>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Data/Hora (Manaus)</th>
                    <th>Distância Detectada</th>
                    <th>Coordenadas GPS</th>
                    <th>Vigente na Hora?</th>
                </tr>
            </thead>
            <tbody>
                {linhas or "<tr><td colspan='4' align='center'>Nenhum registro de proximidade crítica.</td></tr>"}
            </tbody>
        </table>

        <div style="text-align:center; margin-top:30px;" class="no-print">
            <button onclick="window.print()" style="padding:12px 30px; background:#003366; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">IMPRIMIR RELATÓRIO PDF</button>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
