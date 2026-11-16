-- TABELA DE VERSÕES
CREATE TABLE versao (
    id SERIAL PRIMARY KEY,
    data_criacao DATE NOT NULL DEFAULT CURRENT_DATE,
    hora_criacao TIME NOT NULL DEFAULT CURRENT_TIME,
    data_encerramento DATE,
    hora_encerramento TIME,
    versao_ativa BOOLEAN NOT NULL DEFAULT TRUE,
    quantidade_eventos INTEGER DEFAULT 0 CHECK (quantidade_eventos >= 0),
    CHECK (
        (versao_ativa = TRUE AND data_encerramento IS NULL AND hora_encerramento IS NULL) OR
        (versao_ativa = FALSE AND data_encerramento IS NOT NULL AND hora_encerramento IS NOT NULL)
    )
);

-- TABELA DE ENDEREÇOS
CREATE TABLE endereco (
    id_endereco SERIAL PRIMARY KEY,
    nome TEXT,
    endereco TEXT,
    numero TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    cep TEXT,
    pais TEXT,
    longitude NUMERIC,
    latitude NUMERIC,
    CONSTRAINT endereco_unico UNIQUE (
        nome, endereco, numero, complemento, bairro,
        cidade, estado, cep, pais, longitude, latitude
    )
);

-- TABELA DE ORGANIZADORES
CREATE TABLE organizador (
    id_organizador SERIAL PRIMARY KEY,
    nome TEXT,
    descricao TEXT,
    CONSTRAINT organizador_unico UNIQUE (nome, descricao)
);

-- TABELA DE CATEGORIAS
CREATE TABLE categoria (
    id_categoria SERIAL PRIMARY KEY,
    categoria_primaria TEXT,
    categoria_secundaria TEXT,
    CONSTRAINT categoria_unica UNIQUE (categoria_primaria, categoria_secundaria)
);

-- TABELA DE EVENTOS (com sympla_reference_id explicitamente)
CREATE TABLE evento (
    id_evento SERIAL PRIMARY KEY,          -- ID interno único para cada versão do evento
    sympla_reference_id INTEGER NOT NULL,  -- Id do evento no Sympla (igual a id_sympla)
    id_sympla TEXT,
    data_inicio DATE,
    hora_inicio TIME,
    data_fim DATE,
    hora_fim TIME,
    nome TEXT,
    descricao TEXT,
    evento_privado BOOLEAN,
    publicado BOOLEAN,
    cancelado BOOLEAN,
    imagem TEXT,
    url TEXT,
    id_endereco INTEGER REFERENCES endereco(id_endereco),
    id_organizador INTEGER REFERENCES organizador(id_organizador),
    id_categoria INTEGER REFERENCES categoria(id_categoria)
);

-- RELACIONAMENTO N:N ENTRE VERSÃO E EVENTO
CREATE TABLE evento_versao (
    id_versao INTEGER REFERENCES versao(id) ON DELETE CASCADE,
    id_evento INTEGER REFERENCES evento(id_evento) ON DELETE CASCADE,
    PRIMARY KEY (id_versao, id_evento)
);
