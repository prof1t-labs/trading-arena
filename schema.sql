-- Reference schema. The FastAPI app creates equivalent tables through SQLAlchemy.
CREATE TABLE users (
  id varchar(36) PRIMARY KEY,
  name varchar(120) NOT NULL,
  email varchar(320) UNIQUE NOT NULL,
  password_hash varchar(255) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE login_sessions (
  token_hash varchar(64) PRIMARY KEY,
  user_id varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
  user_id varchar(36) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dataset_records (
  id varchar(36) PRIMARY KEY,
  user_id varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  dataset_type varchar(80) NOT NULL,
  external_key varchar(160),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_login_sessions_user_id ON login_sessions(user_id);
CREATE INDEX ix_login_sessions_expires_at ON login_sessions(expires_at);
CREATE INDEX ix_dataset_records_user_id ON dataset_records(user_id);
CREATE INDEX ix_dataset_records_type ON dataset_records(dataset_type);
