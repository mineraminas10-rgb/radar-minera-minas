-- Decisão de 30/09/2026, seguindo a Carta de Revisão/Calibração de Scores M8/M9A:
-- nenhuma fórmula de score está homologada para produção ainda. Por decisão
-- explícita (não literal da carta, que só trata M8/M9A — extensão pedida pela
-- Rapha para os 59 registros atuais de event_scores), marcamos TODOS como
-- 'preliminar', incluindo o caso 830.649/2020 recém-reprocessado (estava
-- 'final' por decisão de que a correção do DADO estava encerrada — mas a
-- carta trata da FÓRMULA, não da correção pontual, então também vira
-- preliminar). Nada é apagado; é só o campo de estágio, aditivo e reversível.
update event_scores set estagio = 'preliminar' where estagio = 'final';
