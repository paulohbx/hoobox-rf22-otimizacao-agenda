# RF-22 — Otimização de Agendamentos Cirúrgicos

Microserviço Python com FastAPI + Google OR-Tools CP-SAT para otimização automática de agendamentos no centro cirúrgico.

## Deploy no Railway

### Passo 1 — Criar conta e novo projeto
1. Acessar https://railway.app
2. Login com GitHub
3. "New Project" → "Deploy from GitHub repo"
4. Selecionar o repositório `hoobox-rf22-otimizacao`

### Passo 2 — Aguardar o deploy
O Railway detecta automaticamente o `Procfile` e o `requirements.txt`.
A instalação do `ortools` demora ~3 minutos — mais que o normal, é esperado.

### Passo 3 — Testar o healthcheck
```
GET https://sua-url.railway.app/health
→ {"status": "ok", "service": "RF-22 Otimização de Agendamentos"}
```

### Passo 4 — Adicionar secret no Supabase (Lovable)
Lovable Cloud → Secrets → adicionar:
- Name: `RF22_SERVICE_URL`
- Value: `https://sua-url.railway.app`

---

## Endpoints

### GET /health
Healthcheck do serviço.

### POST /otimizar

**Input:**
```json
{
  "cirurgias": [
    {
      "procedimento_id": "AGD-001",
      "horario_original": "09:00",
      "duracao_est_min": 120,
      "cirurgiao_id": "CIR-001",
      "especialidade": "Ortopedia",
      "equipamentos": ["Torre de Artroscopia"],
      "sala_preferida": "CC-01"
    }
  ],
  "salas_disponiveis": [
    {
      "sala_id": "CC-01",
      "capacidade_turno_min": 480,
      "equipamentos": ["Torre de Artroscopia", "Bisturi Elétrico"]
    }
  ],
  "preferencias": {
    "objetivo_principal": "maximizar_ocupacao",
    "ordenacao": "longas_primeiro",
    "rigidez_horario": 0.5,
    "preferencias_sala": { "Ortopedia": "CC-01" },
    "limpeza_min": 30
  }
}
```

**Valores válidos para `objetivo_principal`:**
- `maximizar_ocupacao` — maximiza o tempo de sala utilizado *(padrão)*
- `minimizar_termino` — termina o dia o mais cedo possível
- `minimizar_overtime` — minimiza extrapolação do turno

**Valores válidos para `ordenacao`:**
- `longas_primeiro` *(padrão)*
- `curtas_primeiro`
- `ordem_agendamento`

**Output:**
```json
{
  "status": "OPTIMAL",
  "alocacoes": [
    {
      "procedimento_id": "AGD-001",
      "sala": "CC-01",
      "horario_inicio": "07:00",
      "horario_fim": "09:00",
      "cirurgiao_id": "CIR-001",
      "especialidade": "Ortopedia",
      "justificativa": "Solver CP-SAT · objetivo: maximizar_ocupacao"
    }
  ],
  "total_procedimentos": 1,
  "ocupacao_pct": 25.0,
  "objetivo_usado": "maximizar_ocupacao"
}
```

---

## Restrições modeladas

| Tipo | Restrição | Violável? |
|---|---|---|
| Dura | Cada cirurgia alocada exatamente uma vez | Não |
| Dura | Capacidade do turno da sala não excedida | Não |
| Dura | Cirurgião não pode estar em duas salas ao mesmo tempo | Não |
| Dura | Equipamento obrigatório disponível na sala | Não |
| Soft | Preferência de sala por especialidade | Sim (penalizado) |
| Soft | Rigidez do horário original agendado | Sim (penalizado) |

---

## Stack

- **FastAPI** — API REST
- **Google OR-Tools CP-SAT** — solver de otimização combinatória
- **Pydantic** — validação de dados
- **Railway** — deploy e hosting

## Relacionado

- RF-52 Simulação de Impacto: `hoobox-rf52-impacto`
- Playbook de IA: `playbook-ia-centro-cirurgico.html`
