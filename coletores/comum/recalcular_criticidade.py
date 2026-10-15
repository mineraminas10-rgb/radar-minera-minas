"""
Recálculo automático da criticidade de eventos M9A que ficaram PROVISÓRIOS ou PENDENTES DE EVIDÊNCIA (CRIT-V1.2).

Quando entra evidência estruturada (linhas em `evidencias`) e/ou o tipo oficial do SCM
(`evidencias.campo_sustentado = 'descricao_tipo_evento'`), o evento é reclassificado pela MESMA régua e a nova linha de
score é gravada como nova versão (gravar_criticidade): a linha anterior é preservada (vigente=false), nada é apagado.

- Sem tipo oficial: continua classificado pelo texto livre curado, `provisoria=true` (nunca selecionável).
- Com tipo oficial: classifica pelo tipo SCM (como o coletor), `provisoria=false`, origem `tipo_oficial`.
- Com mais de um tipo oficial no evento (caso consolidado), vale o MELHOR ato (maior nível; empate: mais reforços).

Este módulo NÃO é agendado nem chamado por nenhum cron; é uma função/CLI de uso manual ou de um coletor. Nenhuma IA.
O M8 se recalcula quando o comunicado é reprocessado pelo próprio coletor M8 (que já grava a criticidade a cada leitura).
"""
import os
import sys
from datetime import date
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criticidade as c
import criticidade_db as db
import simular_criticidade as sim

CAMPO_TIPO_OFICIAL = "descricao_tipo_evento"


def _ativas(evidencias: List[dict]) -> List[dict]:
    return [e for e in evidencias if not e.get("superseded")]


def _primeiro(evidencias: List[dict], campo: str) -> Optional[str]:
    return next((e.get("trecho_literal") for e in evidencias if e.get("campo_sustentado") == campo and e.get("trecho_literal")), None)


def reclassificar_m9a(evento: dict, evidencias: List[dict], par: dict, referencia: date) -> c.ResultadoCriticidade:
    """`evento`: linha de `events` (id_evento, empresa, data_evento, tipo_evento, decisao, atividade, palavras_chave,
    titulo_fato, impacto_dimensionado, municipio). `evidencias`: linhas de `evidencias` do evento."""
    ev = _ativas(evidencias)
    tipos = [e["trecho_literal"] for e in ev if e.get("campo_sustentado") == CAMPO_TIPO_OFICIAL and e.get("trecho_literal")]
    row = dict(evento)
    row["nev"] = len(ev)
    row["titular_scm"] = _primeiro(ev, "titular")
    row["subst_scm"] = _primeiro(ev, "substancia")
    row["area_scm"] = _primeiro(ev, "area_ha")
    # a data do ato é a do próprio evento (validada na curadoria); o SCM pode trazer várias datas sem par com o tipo
    row["dt_scm"] = evento.get("data_evento")
    if not tipos:
        row["tipo_scm"] = None
        return c.classificar_m9a(sim.entrada_m9a(row), par, referencia)
    melhor = None
    melhor_chave = None
    for tipo in tipos:
        r = c.classificar_m9a(sim.entrada_m9a(dict(row, tipo_scm=tipo)), par, referencia)
        chave = (par["niveis"].index(r.nivel) if r.nivel in par["niveis"] else -1, r.pontuacao,
                 -(r.idade_dias if r.idade_dias is not None else 10 ** 9))
        if melhor is None or chave > melhor_chave:
            melhor, melhor_chave = r, chave
    return melhor


class FonteSupabase:
    """Leitura mínima no banco (somente SELECT). A gravação vai por criticidade_db.gravar_criticidade."""

    def __init__(self, sb):
        self.sb = sb

    def pendentes(self) -> List[dict]:
        linhas = (self.sb.table("event_scores").select("event_id,componentes,versao_score")
                  .eq("vigente", True).like("versao_score", "CRIT-%").execute().data or [])
        out = []
        for l in linhas:
            comp = l.get("componentes") or {}
            if comp.get("modulo") != "M9A":
                continue
            if comp.get("provisoria") or str(comp.get("criticidade", "")).startswith("POTENCIAL_") or comp.get("evidencia_suficiente") is False:
                out.append({"event_id": l["event_id"]})
        return out

    def evento(self, event_id: str) -> dict:
        r = (self.sb.table("events").select("id,id_evento,empresa,empresa_id,municipio,data_evento,tipo_evento,decisao,atividade,"
                                           "palavras_chave,titulo_fato,impacto_dimensionado")
             .eq("id", event_id).execute().data or [])
        return r[0] if r else {}

    def evidencias(self, event_id: str) -> List[dict]:
        return (self.sb.table("evidencias").select("campo_sustentado,trecho_literal,superseded")
                .eq("event_id", event_id).execute().data or [])


def recalcular_pendentes(sb, par: Optional[dict] = None, hoje: Optional[date] = None, fonte=None,
                         gravar: Callable = db.gravar_criticidade, limite: Optional[int] = None) -> Dict[str, object]:
    """Reclassifica os M9A provisórios/pendentes. Devolve um resumo; idempotente (resultado igual = 'inalterado')."""
    par = par or c.carregar_parametros()
    referencia = hoje or date.today()
    fonte = fonte or FonteSupabase(sb)
    resumo = {"examinados": 0, "gravados": 0, "inalterados": 0, "erros": 0, "mudancas": []}
    for item in fonte.pendentes()[: limite or None]:
        resumo["examinados"] += 1
        try:
            ev = fonte.evento(item["event_id"])
            res = reclassificar_m9a(ev, fonte.evidencias(item["event_id"]), par, referencia)
            r = gravar(sb, item["event_id"], res, empresa_id=ev.get("empresa_id"))
            resumo["gravados" if r == "gravado" else "inalterados"] += 1
            if r == "gravado":
                resumo["mudancas"].append({"id_evento": ev.get("id_evento"), "criticidade": res.nivel, "provisoria": res.provisoria})
        except Exception as exc:  # um evento com erro não impede os demais
            resumo["erros"] += 1
            resumo.setdefault("erros_detalhe", []).append(f"{item.get('event_id')}: {exc}")
    return resumo
