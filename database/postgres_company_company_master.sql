CREATE TEMP TABLE company_staging (
    idx TEXT,
    ticker TEXT,
    company_name_final TEXT,
    cik TEXT,
    isin TEXT,
    sector TEXT,
    industry TEXT,
    exchange TEXT
);


-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_company_master_cik ON company_master(cik);
CREATE INDEX IF NOT EXISTS idx_company_master_sector ON company_master(sector);
