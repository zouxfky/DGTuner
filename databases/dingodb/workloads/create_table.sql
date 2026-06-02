CREATE TABLE problem(
    problem_id int,
    title varchar(255),
    content varchar(255),
    answer varchar(32),
    score DOUBLE,
    `type` int,
    typetext varchar(32),
    `location` varchar(32),
    exercise_id varchar(32),
    `language` varchar(32),
    contentEmbedding float array not null,
    feature_id int not null,
    PRIMARY KEY (problem_id),
    index title_index (title) ENGINE=TXN_LSM,
    index answer_index (answer) ENGINE=TXN_LSM,
    index score_index (score) ENGINE=TXN_LSM,
    index type_index (`type`) ENGINE=TXN_LSM,
    index typetext_index (typetext) ENGINE=TXN_LSM,
    index location_index (`location`) ENGINE=TXN_LSM,
    index exercise_id_index (exercise_id) ENGINE=TXN_LSM,
    index language_index (`language`) ENGINE=TXN_LSM,
    index contentEmbedding_index vector(feature_id, contentEmbedding) partition by hash partitions=10 parameters(type=hnsw, metricType=L2, dimension=768, efConstruction=500, nlinks=100)
);

CREATE TABLE reply(
    id varchar(64),
    user_id varchar(64),
    `text` TEXT,
    create_time timestamp,
    textEmbedding float array not null,
    feature_id int not null,
    PRIMARY KEY (id),
    index user_id_index (user_id) ENGINE=TXN_LSM,
    index textEmbedding_index vector(feature_id, textEmbedding) partition by hash partitions=5 parameters(type=hnsw, metricType=L2, dimension=768, efConstruction=40, nlinks=32)
);

CREATE TABLE comments(
    id varchar(64),
    user_id varchar(64),
    `text` TEXT,
    create_time timestamp,
    resource_id varchar(64),
    textEmbedding float array not null,
    feature_id int not null,
    index user_id_index (user_id),
    PRIMARY KEY (id),
    index textEmbedding_index vector(feature_id, textEmbedding) partition by hash partitions=5 parameters(type=hnsw, metricType=L2, dimension=768, efConstruction=40, nlinks=32)
);

CREATE TABLE user_problem(
    id varchar(64),
    problem_id varchar(64),
    user_id varchar(64),
    log_id varchar(64),
    is_correct int,
    `attempts` int,
    `score` float,
    submit_time timestamp,
    PRIMARY KEY (id),
    index problem_id_index (problem_id) ENGINE=TXN_LSM,
    index user_id_index (user_id) ENGINE=TXN_LSM,
    index log_id_index (log_id) ENGINE=TXN_LSM,
    index is_correct_index (is_correct) ENGINE=TXN_LSM,
    index attempts_index (`attempts`) ENGINE=TXN_LSM,
    index score_index (`score`) ENGINE=TXN_LSM
);

CREATE TABLE user(
    id varchar(128),
    name varchar(128),
    gender int,
    school varchar(128),
    year_of_birth int,
    course_order varchar(255),
    enroll_time varchar(255),
    PRIMARY KEY (id),
    index name_index (name) ENGINE=TXN_LSM,
    index gnder_index (gender) ENGINE=TXN_LSM,
    index school_index (school) ENGINE=TXN_LSM,
    index year_of_birth_index (year_of_birth) ENGINE=TXN_LSM,
    index course_order_index (course_order) ENGINE=TXN_LSM,
    index enroll_time_index (enroll_time) ENGINE=TXN_LSM
);

CREATE TABLE reply_comments(
    id varchar(64),
    comments_id varchar(64),
    reply_id varchar(64),
    submit_time timestamp,
    PRIMARY KEY (id),
    index comments_id_index (comments_id) ENGINE=TXN_LSM,
    index reply_id_index (reply_id) ENGINE=TXN_LSM
);