-- ROLLBACK (NÃO APLICADO) de 20261018_ia_assistida_leitura_admin.sql. Remove só a função; nenhuma tabela/dado é tocado.
drop function if exists public.ia_assistida_evento(uuid);
