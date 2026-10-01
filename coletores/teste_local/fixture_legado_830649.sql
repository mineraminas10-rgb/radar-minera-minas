-- Fixture LOCAL apenas para testar reprocessamento_830649_2020.sql contra a
-- réplica local — replica o estado legado de produção (não é usado em
-- produção, só para validar a transação antes de rodar de verdade).
-- Nota: o enum local status_editorial está desatualizado (não tem
-- 'liberado_para_pre_release', que existe em produção) — uso 'publicado'
-- como substituto só para o teste local não quebrar; não afeta a lógica da
-- transação, que nunca altera status_editorial.

INSERT INTO empresas (id, nome, slug, ativa)
VALUES ('4a8f5089-7662-4b38-a07b-907b76428a88', 'Radar Minera Minas (fixture)', 'radar-minera-minas-fixture-830649', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO sources (id, nome, url_base, modulo, empresa_id, ativa)
VALUES ('cda24b27-5a09-4b44-87f1-daa1100608d7', 'ANM - SCM Microdados',
        'https://dadosabertos.anm.gov.br/SCM/microdados/', 'M9A_anm_movimentacoes',
        '4a8f5089-7662-4b38-a07b-907b76428a88', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO execucoes (id, id_execucao, inicio, fim, ambiente, empresa_id)
VALUES ('fe2b4bb8-bcee-49f3-8b4b-c796e5a898ce', 'M9A-ANM-20260919-01', '2026-01-01', '2026-09-19',
        null, '4a8f5089-7662-4b38-a07b-907b76428a88')
ON CONFLICT (id) DO NOTHING;

INSERT INTO events (id, id_evento, modulo, execucao_criacao_id, empresa_id, processo, empresa, municipio,
                     status_editorial, grau_completude, cnpj)
VALUES ('5715fbda-7112-4bba-807e-b2651407201d', 'anm-m9a-aguas-ferreas-gu61-830649-2020',
        'M9A_anm_movimentacoes', 'fe2b4bb8-bcee-49f3-8b4b-c796e5a898ce',
        '4a8f5089-7662-4b38-a07b-907b76428a88', '830.649/2020', 'AGUAS FERREAS MINERACAO LTDA',
        'Rio Casca / São Pedro dos Ferros', 'em_apuracao', 'Alta', null)
ON CONFLICT (id) DO NOTHING;

INSERT INTO event_scores (id, event_id, score_bruto, versao_score, score_normalizado, prioridade,
                           vigente, empresa_id, estagio)
VALUES ('3f0472e6-16ff-4ca9-89bf-9e41c690e247', '5715fbda-7112-4bba-807e-b2651407201d',
        86, 'SCORE-M9A-V0.2', 86, 'A', true, '4a8f5089-7662-4b38-a07b-907b76428a88', 'final')
ON CONFLICT (id) DO NOTHING;
