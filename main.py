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
from geopy.geocoders import Nominatim
import uvicorn

# --- CONFIGURAÇÃO DE TIMEZONE (MANAUS/AMAZONAS) ---
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
    data_validade = Column(String) # Formato DD/MM/AAAA

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

# --- CONFIGURAÇÃO DO WEBHOOK (COLE SEU LINK AQUI) ---
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url, vigente):
    status_juridico = "VIGENTE - AUTORIZA PRISÃO" if vigente else "EXPIRADA - MONITORAMENTO INFORMATIVO"
    payload = {
        "timestamp": datetime.now(tz_am).strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO DETECTADA",
        "status_juridico": status_juridico,
        "vitima": vitima,
        "contato_vitima": telefone,
        "distancia_apurada": f"{round(distancia, 2)}m",
        "mapa_google": maps_url,
        "foto_agressor": foto_url or "https://via.placeholder.com/150",
        "alerta": "⚠️ ATENÇÃO: Ação necessária conforme status jurídico."
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(WEBHOOK_URL, json=payload)
            return f"Sucesso ({status_juridico})"
        except: return "Erro na conexão com Webhook"

def verificar_vigencia(data_str: str) -> bool:
    try:
        agora = datetime.now(tz_am)
        data_exp = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        data_exp_final = tz_am.localize(datetime.combine(data_exp.date(), time(23, 59, 59)))
        return agora <= data_exp_final
    except: return True

# --- APP FASTAPI ---
app = FastAPI(title="Sentinela Mulher - Amazonas")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(...), vitima: str = Body(...), telefone: str = Body(...),
    validade: str = Body(...), raio: float = Body(500.0), foto: str = Body(None),
    db: Session = Depends(get_db)
):
    # .strip() para evitar o erro 404 por espaços invisíveis
    nova = MedidaProtetiva(processo_id=processo.strip(), nome_vitima=vitima, telefone_vitima=telefone,
                           distancia_minima=raio, foto_agressor_url=foto, data_validade=validade)
    db.add(nova); db.commit()
    return {"status": "Processo Cadastrado com Sucesso"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...), ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso.strip()).first()
    if not medida:
        raise HTTPException(status_code=404, detail="ID não encontrado. Cadastre a medida primeiro.")

    vigente = verificar_vigencia(medida.data_validade)
    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    notif = "N/A"
    
    # O sistema sempre processa as informações se houver proximidade, ignorando a validade para fins de inteligência
    if dist <= medida.distancia_minima:
        maps = f"https://www.google.com/maps?q={ag_lat},{ag_long}"
        notif = await disparar_alerta_urgente(medida.telefone_vitima, dist, medida.nome_vitima, maps, medida.foto_agressor_url, vigente)
        
        log = HistoricoViolacao(medida_id=medida.id, distancia_detectada=round(dist, 2),
                               lat_agressor=ag_lat, long_agressor=ag_long, 
                               status_notificacao=notif, medida_vigente_na_hora="SIM" if vigente else "NÃO")
        db.add(log); db.commit()

    return {
        "status": "🚨 VIOLAÇÃO DETECTADA" if dist <= medida.distancia_minima else "DENTRO DA NORMALIDADE",
        "vigencia_juridica": "VIGENTE" if vigente else "EXPIRADA (Apenas Monitoramento)",
        "dados_agressor": {
            "lat": ag_lat, "long": ag_long, "foto": medida.foto_agressor_url
        },
        "dados_vitima": {
            "nome": medida.nome_vitima, "contato": medida.telefone_vitima
        },
        "distancia_apurada": f"{round(dist, 2)}m",
        "alerta_central": notif
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id.strip()).first()
    if not medida: return "<h1>Processo não localizado</h1>"
    
    vigente_hoje = verificar_vigencia(medida.data_validade)
    cor = "#28a745" if vigente_hoje else "#dc3545"

    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    linhas = ""
    for v in violacoes:
        v_cor = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{v.lat_agressor}, {v.long_agressor}</td><td style='color:{v_cor}; font-weight:bold;'>{v.medida_vigente_na_hora}</td></tr>"

    return f"""
    <html>
    <head><style>
        body {{ font-family: sans-serif; padding: 40px; }}
        .header {{ border-bottom: 4px solid #003366; text-align: center; }}
        .badge {{ background: {cor}; color: white; padding: 10px; border-radius: 5px; font-weight: bold; display: inline-block; }}
        .box {{ background: #f8f9fa; padding: 20px; border-radius: 10px; display: flex; align-items: center; border: 1px solid #ddd; margin-top:10px; }}
        .foto {{ width: 120px; border: 3px solid #003366; border-radius: 5px; margin-right: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background: #003366; color: white; }}
    </style></head>
    <body>
        <div class="header">
            <h2>RELATÓRIO PERICIAL - SENTINELA MULHER</h2>
            <div class="badge">STATUS JURÍDICO ATUAL: {'VIGENTE' if vigente_hoje else 'EXPIRADO'}</div>
        </div>
        <div class="box">
            <img src="{medida.foto_agressor_url or 'https://via.placeholder.com/150'}" class="foto">
            <div>
                <p><b>PROCESSO:</b> {medida.processo_id} | <b>VÍTIMA:</b> {medida.nome_vitima}</p>
                <p><b>VALIDADE NO SISTEMA:</b> {medida.data_validade}</p>
                <p><b>INSTRUÇÃO:</b> { "EFETUAR PRISÃO" if vigente_hoje else "MONITORAMENTO DE REINCIDÊNCIA" }</p>
            </div>
        </div>
        <table>
            <thead><tr><th>Data/Hora (Manaus)</th><th>Distância</th><th>Coordenadas da Invasão</th><th>Vigente na Hora?</th></tr></thead>
            <tbody>{linhas or "<tr><td colspan='4' style='text-align:center;'>Nenhum registro de proximidade crítica.</td></tr>"}</tbody>
        </table>
        <br><button onclick="window.print()">Gerar PDF do Relatório</button>
    </body></html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
