import os
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

# --- CONFIGURAÇÃO DE TIMEZONE ---
tz_am = pytz.timezone('America/Manaus')

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
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
app = FastAPI(title="Sentinela Mulher - Amazonas")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial_2026", "token_type": "bearer"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial_2026":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return token

# --- LÓGICA DE NEGÓCIO ---
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url, vigente):
    status_juridico = "VIGENTE" if vigente else "EXPIRADA"
    payload = {
        "timestamp": datetime.now(tz_am).strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DETECTADA",
        "status": status_juridico,
        "vitima": vitima,
        "distancia": f"{round(distancia, 2)}m",
        "mapa": maps_url,
        "foto_agressor": foto_url
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try: await client.post(WEBHOOK_URL, json=payload)
        except: pass

def verificar_vigencia(data_str: str) -> bool:
    try:
        agora = datetime.now(tz_am)
        data_exp = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        data_exp_final = tz_am.localize(datetime.combine(data_exp.date(), time(23, 59, 59)))
        return agora <= data_exp_final
    except: return True

# --- ENDPOINTS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(...), vitima: str = Body(...), telefone: str = Body(...),
    validade: str = Body(...), raio: float = Body(500.0), foto: str = Body(None),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    nova = MedidaProtetiva(processo_id=processo.strip(), nome_vitima=vitima, telefone_vitima=telefone,
                           distancia_minima=raio, foto_agressor_url=foto, data_validade=validade)
    db.add(nova); db.commit()
    return {"status": "Processo Cadastrado com Sucesso"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...), ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso.strip()).first()
    if not medida: raise HTTPException(status_code=404, detail="Não cadastrado")

    vigente = verificar_vigencia(medida.data_validade)
    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    
    if dist <= medida.distancia_minima:
        maps = f"http://maps.google.com/?q={ag_lat},{ag_long}"
        await disparar_alerta_urgente(medida.telefone_vitima, dist, medida.nome_vitima, maps, medida.foto_agressor_url, vigente)
        
        log = HistoricoViolacao(medida_id=medida.id, distancia_detectada=round(dist, 2),
                               lat_agressor=ag_lat, long_agressor=ag_long, 
                               status_notificacao="Enviado", medida_vigente_na_hora="SIM" if vigente else "NÃO")
        db.add(log); db.commit()

    return {
        "violacao": dist <= medida.distancia_minima,
        "vigencia": "ATIVA" if vigente else "EXPIRADA",
        "distancia": f"{round(dist, 2)}m",
        "agressor": {"foto": medida.foto_agressor_url},
        "vitima": {"nome": medida.nome_vitima}
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id.strip()).first()
    if not medida: return "<h1>Processo Inexistente</h1>"
    
    vigente_hoje = verificar_vigencia(medida.data_validade)
    cor_status = "#28a745" if vigente_hoje else "#dc3545"
    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    
    linhas = ""
    for v in violacoes:
        v_cor = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{v.lat_agressor}, {v.long_agressor}</td><td style='color:{v_cor}; font-weight:bold;'>{v.medida_vigente_na_hora}</td></tr>"

    return f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; padding: 40px; color: #333; }}
            .header {{ text-align: center; border-bottom: 5px solid #003366; padding-bottom: 10px; margin-bottom: 20px; }}
            .status-badge {{ background: {cor_status}; color: white; padding: 8px 15px; border-radius: 20px; font-weight: bold; display: inline-block; }}
            .container {{ display: flex; border: 1px solid #ddd; padding: 20px; background: #fdfdfd; border-radius: 8px; }}
            .foto-container {{ text-align: center; margin-right: 30px; }}
            .foto-agressor {{ width: 160px; height: 200px; border: 4px solid #003366; border-radius: 4px; object-fit: cover; background: #eee; display: block; }}
            .label-foto {{ margin-top: 5px; font-size: 10px; font-weight: bold; color: #003366; text-transform: uppercase; }}
            .info {{ flex-grow: 1; }}
            .info h3 {{ margin: 0 0 10px 0; color: #003366; border-bottom: 1px solid #eee; }}
            .info p {{ margin: 5px 0; font-size: 14px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; font-size: 13px; }}
            th {{ background: #003366; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            .footer {{ margin-top: 50px; text-align: center; font-size: 11px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }}
            @media print {{ .no-print {{ display: none; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2 style="margin:0;">SISTEMA SENTINELA MULHER</h2>
            <p style="margin:5px 0; font-size: 12px;">SECRETARIA DE SEGURANÇA PÚBLICA - ESTADO DO AMAZONAS</p>
            <div class="status-badge">STATUS JURÍDICO: {'VIGENTE' if vigente_hoje else 'EXPIRADO'}</div>
        </div>

        <div class="container">
            <div class="foto-container">
                <img src="{medida.foto_agressor_url or 'https://via.placeholder.com/160x200?text=SEM+FOTO'}" 
                     alt="Foto do Agressor" class="foto-agressor" onerror="this.src='https://via.placeholder.com/160x200?text=ERRO+NA+IMAGEM'">
                <div class="label-foto">Identificação do Agressor</div>
            </div>
            <div class="info">
                <h3>Dados do Monitoramento</h3>
                <p><b>Número do Processo:</b> {medida.processo_id}</p>
                <p><b>Vítima Protegida:</b> {medida.nome_vitima}</p>
                <p><b>Data Limite da Medida:</b> {medida.data_validade}</p>
                <p><b>Raio de Exclusão:</b> {medida.distancia_minima} metros</p>
                <p><b>Instrução Policial:</b> { "EFETUAR PRISÃO EM CASO DE VIOLAÇÃO" if vigente_hoje else "VERIFICAR RENOVAÇÃO / MONITORAMENTO INFORMATIVO" }</p>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Data/Hora (Manaus)</th>
                    <th>Distância Detectada</th>
                    <th>Coordenadas GPS</th>
                    <th>Vigência Legal?</th>
                </tr>
            </thead>
            <tbody>
                {linhas or "<tr><td colspan='4' align='center'>Nenhum registro de violação encontrado.</td></tr>"}
            </tbody>
        </table>

        <div class="footer">
            Relatório Gerado por Investigador Clodoaldo S. Viana - Data: {datetime.now(tz_am).strftime('%d/%m/%Y %H:%M:%S')}
        </div>
        
        <div style="text-align:center; margin-top: 20px;" class="no-print">
            <button onclick="window.print()" style="padding:10px 20px; background:#003366; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">Imprimir / Salvar PDF</button>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
