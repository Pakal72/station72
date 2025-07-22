ALTER TABLE pages
ADD COLUMN delai_fermeture INTEGER DEFAULT NULL COMMENT 'Délai en secondes avant fermeture automatique',
ADD COLUMN page_suivante INTEGER DEFAULT NULL COMMENT 'id_page cible en cas de transition automatique';
