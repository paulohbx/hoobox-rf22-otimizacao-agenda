from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from ortools.sat.python import cp_model

app = FastAPI(title="RF-22 — Otimização de Agendamentos", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Modelos ───────────────────────────────────────────────────────

class Cirurgia(BaseModel):
    procedimento_id: str
    horario_original: str          # "HH:MM"
    duracao_est_min: int
    cirurgiao_id: str
    especialidade: str
    equipamentos: List[str] = []
    sala_preferida: Optional[str] = None

class Sala(BaseModel):
    sala_id: str
    capacidade_turno_min: int      # ex: 480 = 8h
    equipamentos: List[str] = []

class Preferencias(BaseModel):
    objetivo_principal: str = "maximizar_ocupacao"
    ordenacao: str = "longas_primeiro"
    rigidez_horario: float = 0.5   # 0.0 = flexível, 1.0 = rígido
    preferencias_sala: Dict[str, str] = {}
    limpeza_min: int = 30

class OtimizarRequest(BaseModel):
    cirurgias: List[Cirurgia]
    salas_disponiveis: List[Sala]
    preferencias: Preferencias

# ─── Helpers ───────────────────────────────────────────────────────

def format_time(minutes: int) -> str:
    return f"{(minutes//60)%24:02d}:{minutes%60:02d}"

def ordenar_cirurgias(cirurgias, criterio):
    if criterio == "longas_primeiro":
        return sorted(cirurgias, key=lambda x: x.duracao_est_min, reverse=True)
    elif criterio == "curtas_primeiro":
        return sorted(cirurgias, key=lambda x: x.duracao_est_min)
    return cirurgias  # ordem_agendamento — mantém original

# ─── Endpoint /otimizar ────────────────────────────────────────────

@app.post("/otimizar")
def otimizar(req: OtimizarRequest):
    pref = req.preferencias
    cirurgias = ordenar_cirurgias(req.cirurgias, pref.ordenacao)
    salas = req.salas_disponiveis
    n_c, n_s = len(cirurgias), len(salas)

    model = cp_model.CpModel()
    x = {(c, s): model.new_bool_var(f"x_c{c}_s{s}")
         for c in range(n_c) for s in range(n_s)}

    # RESTRIÇÃO 1: cada cirurgia alocada exatamente uma vez
    for c in range(n_c):
        model.add_exactly_one(x[c, s] for s in range(n_s))

    # RESTRIÇÃO 2: capacidade da sala não excedida
    for s, sala in enumerate(salas):
        model.add(
            sum(x[c, s] * (cirurgias[c].duracao_est_min + pref.limpeza_min)
                for c in range(n_c)) <= sala.capacidade_turno_min
        )

    # RESTRIÇÃO 3: cirurgião não pode estar em duas salas ao mesmo tempo
    for cir_id in set(c.cirurgiao_id for c in cirurgias):
        idx = [i for i, c in enumerate(cirurgias) if c.cirurgiao_id == cir_id]
        if len(idx) > 1:
            for s in range(n_s):
                model.add(sum(x[i, s] for i in idx) <= 1)

    # RESTRIÇÃO 4: equipamento obrigatório deve estar disponível na sala
    for c, cir in enumerate(cirurgias):
        for s, sala in enumerate(salas):
            for eq in cir.equipamentos:
                if eq not in sala.equipamentos:
                    model.add(x[c, s] == 0)

    # SOFT: preferência de sala por especialidade
    pen_sala = []
    for c, cir in enumerate(cirurgias):
        sala_pref = pref.preferencias_sala.get(cir.especialidade)
        if sala_pref:
            for s, sala in enumerate(salas):
                if sala.sala_id != sala_pref:
                    pen_sala.append(x[c, s])

    # SOFT: rigidez do horário original
    pen_horario = []
    if pref.rigidez_horario > 0:
        for c, cir in enumerate(cirurgias):
            if cir.sala_preferida:
                orig_s = next((s for s, sala in enumerate(salas)
                               if sala.sala_id == cir.sala_preferida), None)
                if orig_s is not None:
                    for s in range(n_s):
                        if s != orig_s:
                            pen_horario.append(x[c, s])

    # FUNÇÃO OBJETIVO — dinâmica conforme preferência do gestor
    ocupacao = sum(x[c, s] * cirurgias[c].duracao_est_min
                   for c in range(n_c) for s in range(n_s))
    p_sala = sum(pen_sala) if pen_sala else 0
    p_hor  = sum(pen_horario) if pen_horario else 0
    rigidez_peso = int(pref.rigidez_horario * 10)

    if pref.objetivo_principal == "maximizar_ocupacao":
        model.maximize(ocupacao - p_sala * 5 - p_hor * rigidez_peso)
    elif pref.objetivo_principal == "minimizar_overtime":
        model.minimize(p_sala * 5 + p_hor * rigidez_peso)
    else:  # minimizar_termino
        model.maximize(ocupacao - p_sala * 3 - p_hor * rigidez_peso)

    # ─── Resolver ──────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"erro": "Nenhuma solução viável encontrada", "alocacoes": []}

    # ─── Montar resultado ──────────────────────────────────────────
    alocacoes = []
    hora_por_sala = {s: 7 * 60 for s in range(n_s)}  # início às 07:00

    for c, cir in enumerate(cirurgias):
        for s, sala in enumerate(salas):
            if solver.value(x[c, s]):
                inicio = hora_por_sala[s]
                fim = inicio + cir.duracao_est_min
                alocacoes.append({
                    "procedimento_id": cir.procedimento_id,
                    "sala": sala.sala_id,
                    "horario_inicio": format_time(inicio),
                    "horario_fim": format_time(fim),
                    "cirurgiao_id": cir.cirurgiao_id,
                    "especialidade": cir.especialidade,
                    "justificativa": f"Solver CP-SAT · objetivo: {pref.objetivo_principal}"
                })
                hora_por_sala[s] = fim + pref.limpeza_min

    cap_total = sum(s.capacidade_turno_min for s in salas)
    total_min = sum(c.duracao_est_min for c in cirurgias)

    return {
        "status": solver.status_name(status),
        "alocacoes": sorted(alocacoes, key=lambda a: (a["sala"], a["horario_inicio"])),
        "total_procedimentos": len(alocacoes),
        "ocupacao_pct": round(total_min / cap_total * 100, 1),
        "objetivo_usado": pref.objetivo_principal,
    }

@app.get("/health")
def health():
    return {"status": "ok", "service": "RF-22 Otimização de Agendamentos"}
