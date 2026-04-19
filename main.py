import os
from datetime import datetime
import httpx
from typing import Optional

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import uvicorn

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./sentinela_mulher.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELOS DO BANCO ---
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
    timestamp = Column(DateTime, default=datetime.utcnow)
    distancia_detectada = Column(Float)
    lat_agressor = Column(Float)
    long_agressor = Column(Float)
    status_notificacao = Column(String)
    medida_vigente_na_hora = Column(String) # "SIM" ou "NÃO" para resguardo jurídico

Base.metadata.create_all(bind=engine)

# --- CONFIGURAÇÃO DE ALERTA REAL ---
# Substitua pelo seu link do Webhook.site para a demonstração
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url, vigente):
    """Envia o Alerta Real com Status de Vigência Jurídica"""
    status_juridico = "VIGENTE - AUTORIZA PRISÃO" if vigente else "EXPIRADA - INFORMATIVO"
    payload = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO",
        "status_juridico": status_juridico,
        "vitima": vitima,
        "contato_vitima": telefone,
        "distancia": f"{round(distancia, 2)} metros",
        "mapa_localizacao": maps_url,
        "foto_agressor": foto_url or "https://via.placeholder.com/150",
        "mensagem": f"🚨 ALERTA SENTINELA: Invasão detectada a {round(distancia, 2)}m da vítima {vitima}."
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(WEBHOOK_URL, json=payload)
            return f"Alerta Disparado ({status_juridico})"
        except:
            return "Falha ao contactar Central"

# --- INICIALIZAÇÃO E SEGURANÇA ---
app = FastAPI(title="Sentinela Mulher - Projeto Investigador Clodoaldo")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial", "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Acesso Negado")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial": raise HTTPException(status_code=401)
    return token

# --- ENDPOINTS OPERACIONAIS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(..., example="2026-AM-001"),
    vitima: str = Body(..., example="Maria da Silva"),
    telefone: str = Body(..., example="5592999999999"),
    validade: str = Body(..., example="31/12/2026", description="Data de validade DD/MM/AAAA"),
    raio: float = Body(500.0),
    foto: str = Body(None, example="https://link-da-foto.com/agressor.jpg"),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    nova = MedidaProtetiva(
        processo_id=processo, nome_vitima=vitima, telefone_vitima=telefone,
        distancia_minima=raio, foto_agressor_url=foto, data_validade=validade
    )
    db.add(nova)
    db.commit()
    return {"status": "Proteção Cadastrada com Sucesso"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...), ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso).first()
    if not medida: raise HTTPException(status_code=404, detail="Processo inexistente")

    # VALIDAÇÃO JURÍDICA AUTOMÁTICA
    vigente = True
    try:
        data_exp = datetime.strptime(medida.data_validade, "%d/%m/%Y")
        if datetime.now() > data_exp: vigente = False
    except: vigente = True # Se erro no formato, assume vigente por segurança

    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    notif = "N/A"
    status_msg = "SISTEMA SEGURO"
    
    if dist <= medida.distancia_minima:
        status_msg = "🚨 ALERTA: VIOLAÇÃO DE PERÍMETRO! 🚨"
        maps = f"https://www.google.com/maps?q={ag_lat},{ag_long}"
        
        # Disparo do Alerta Real com Foto e Localização
        notif = await disparar_alerta_urgente(
            medida.telefone_vitima, dist, medida.nome_vitima, maps, 
            medida.foto_agressor_url, vigente
        )
        
        # Registro no Histórico de Provas (Cadeia de Custódia)
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(dist, 2),
            lat_agressor=ag_lat, long_agressor=ag_long, 
            status_notificacao=notif, medida_vigente_na_hora="SIM" if vigente else "NÃO"
        )
        db.add(log); db.commit()

    return {
        "status": status_msg, 
        "vigencia_juridica": "ATIVA" if vigente else "EXPIRADA",
        "distancia_apurada": f"{round(dist, 2)}m",
        "notificacao_central": notif
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id).first()
    if not medida: return "<h1>Erro: Medida Protetiva não encontrada.</h1>"
    
    # Checagem de vigência para o cabeçalho do relatório
    vigente_hoje = True
    try:
        data_exp = datetime.strptime(medida.data_validade, "%d/%m/%Y")
        if datetime.now() > data_exp: vigente_hoje = False
    except: vigente_hoje = True

    cor_status = "#28a745" if vigente_hoje else "#dc3545"
    texto_status = "VIGENTE / ATIVA" if vigente_hoje else "EXPIRADA / VENCIDA"

    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    linhas = ""
    geo = Nominatim(user_agent="sentinela_am_clodoaldo")

    for v in violacoes:
        try:
            loc = geo.reverse(f"{v.lat_agressor}, {v.long_agressor}", timeout=3)
            end = loc.address if loc else f"Coord: {v.lat_agressor}, {v.long_agressor}"
        except: end = "Endereço registrado via GPS"
        
        cor_v = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        
        linhas += f"""
        <tr>
            <td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{v.distancia_detectada}m</td>
            <td style='font-size:12px;'>{end}</td>
            <td style='color:{cor_v}; font-weight:bold;'>{v.medida_vigente_na_hora}</td>
        </tr>
        """

    return f"""
    <html>
    <head><style>
        body {{ font-family: 'Segoe UI', Arial; padding: 40px; line-height: 1.6; }}
        .header {{ border-bottom: 5px solid #003366; text-align: center; padding-bottom: 10px; }}
        .badge {{ background: {cor_status}; color: white; padding: 8px 15px; border-radius: 20px; font-weight: bold; display: inline-block; margin-top: 10px; }}
        .box {{ background: #f9f9f9; border: 1px solid #ddd; padding: 20px; margin: 20px 0; display: flex; border-radius: 8px; }}
        .foto {{ width: 130px; height: 160px; border: 3px solid #003366; border-radius: 5px; object-fit: cover; margin-right: 25px; background: #eee; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background: #003366; color: white; }}
        .footer {{ margin-top: 40px; font-size: 11px; text-align: center; color: #888; border-top: 1px solid #eee; padding-top: 10px; }}
        @media print {{ .btn {{ display: none; }} }}
    </style></head>
    <body>
        <div class="header">
            <h2>RELATÓRIO PERICIAL DE MONITORAMENTO ELETRÔNICO</h2>
            <p>SISTEMA SENTINELA MULHER | ESTADO DO AMAZONAS</p>
            <div class="badge">STATUS JURÍDICO: {texto_status}</div>
        </div>
        <div class="box">
            <img src="{medida.foto_agressor_url or 'https://via.placeholder.com/150?text=AGRESSOR'}" class="foto">
            <div>
                <p><b>Nº PROCESSO:</b> {medida.processo_id}</p>
                <p><b>VÍTIMA:</b> {medida.nome_vitima}</p>
                <p><b>VENCIMENTO DA MEDIDA:</b> {medida.data_validade}</p>
                <p><b>DIRETRIZ POLICIAL:</b> { "EFETUAR PRISÃO EM CASO DE VIOLAÇÃO" if vigente_hoje else "VERIFICAR RENOVAÇÃO / INFORMAR JUDICIÁRIO" }</p>
            </div>
        </div>
        <table>
            <thead><tr><th>Data/Hora</th><th>Distância</th><th>Localização da Invasão (Endereço)</th><th>Estava Vigente?</th></tr></thead>
            <tbody>{linhas or "<tr><td colspan='4' style='text-align:center;'>Nenhuma violação detectada até o presente momento.</td></tr>"}</tbody>
        </table>
        <div class="footer">Relatório extraído por Investigador Clodoaldo S. Viana - Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</div>
        <br><button class="btn" onclick="window.print()" style="padding:10px 20px; background:#003366; color:white; border:none; border-radius:5px; cursor:pointer;">Gerar PDF / Imprimir</button>
    </body></html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
