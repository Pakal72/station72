ALTER TABLE pages
ADD COLUMN delai_fermeture INTEGER DEFAULT NULL COMMENT 'Délai en secondes avant fermeture automatique',
ADD COLUMN page_suivante INTEGER DEFAULT NULL COMMENT 'id_page cible en cas de transition automatique',
ADD COLUMN musique TEXT DEFAULT NULL COMMENT 'Chemin du fichier musique',
ADD COLUMN image_fond TEXT DEFAULT NULL COMMENT 'Chemin de l''image de fond';

ALTER TABLE pages
ADD COLUMN enigme_texte TEXT DEFAULT NULL COMMENT 'Texte de l''énigme',
ADD COLUMN bouton_texte TEXT DEFAULT NULL COMMENT 'Libellé du bouton',
ADD COLUMN erreur_texte TEXT DEFAULT NULL COMMENT 'Message en cas d''erreur';

ALTER TABLE pages
ADD COLUMN est_aide BOOLEAN DEFAULT FALSE COMMENT 'Page d''aide';

ALTER TABLE jeux
ADD COLUMN ia_nom TEXT DEFAULT NULL COMMENT 'Nom de l\'IA';

ALTER TABLE jeux
ADD COLUMN nom_de_la_voie TEXT DEFAULT NULL COMMENT 'Nom de la voie',
ADD COLUMN voie_actif BOOLEAN DEFAULT FALSE COMMENT 'Voie active';

CREATE TABLE transitions (
    id_transition SERIAL PRIMARY KEY,
    id_page_source INTEGER NOT NULL,
    intention VARCHAR(255) NOT NULL,
    id_page_cible INTEGER NOT NULL,
    condition_flag VARCHAR(100) DEFAULT NULL,
    valeur_condition VARCHAR(100) DEFAULT NULL,
    priorite INTEGER DEFAULT 1,
    reponse_systeme TEXT DEFAULT NULL,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_page_source FOREIGN KEY (id_page_source) REFERENCES pages(id_page),
    CONSTRAINT fk_page_cible FOREIGN KEY (id_page_cible) REFERENCES pages(id_page)
);
