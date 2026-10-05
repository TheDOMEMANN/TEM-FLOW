Ce fichier README a été généré le [2026-03-20] par [Joaquin AMELLER PAVEZ].

Dernière mise-à-jour le : [2026-03-26].

# INFORMATIONS GENERALES

## Titre du jeu de données : Dataset of produce supply flows in Brazzaville: A survey of traders.
 
## DOI: https://doi.org/10.18167/DVN1/DAMXAW
 
## Adresse de contact : joaquin.ameller@cirad.fr
 
# INFORMATIONS METHODOLOGIQUES

## Description des sources et méthodes utilisées pour collecter et générer les données :

Les données ont été collectées au moyen d’enquêtes de marché structurées menées à Brazzaville, en République du Congo, sur une journée pour chacune des deux périodes saisonnières (avril et août 2022). L’objectif était de documenter l’origine, les quantités et les prix de certains légumes commercialisés sur les marchés urbains de gros et de détail.

Un travail d’inventaire initial a permis d’identifier 58 marchés de détail en activité à Brazzaville. À partir de cet inventaire, 14 marchés ont été sélectionnés afin de capturer la distribution géographique des marchés dans la ville, ainsi que la diversité de leur taille et des profils de clientèle. Les marchés de détail enquêtés étaient : Total, Ouenzé, Texaco-La Tsiémé, Moungali, Poto-Poto, Talangaï, Mikalou, Mfilou, Bacongo, Makélékélé, Marché Plateau, Marché Commission, Marché Bourreau et Marché Tsiémé. Ils représentent environ un tiers de l’ensemble des vendeurs des marchés de détail. Par ailleurs, les six marchés de gros approvisionnant la ville ont été intégralement enquêtés : Commission, Bourreau, Hugos, Coaster, Texaco-Tsiémé et Kibéliba.

Dans chaque marché, les commerçants vendant un ou plusieurs des légumes sélectionnés ont été approchés et invités à participer à l’enquête. Les données ont été collectées à l’aide de questionnaires structurés administrés auprès des commerçants. Ces questionnaires ont permis de renseigner le produit vendu, son origine, l’unité de vente, le nombre d’unités commercialisées ainsi que le prix observé par unité le jour de l’enquête. Des questionnaires distincts ont été utilisés pour les marchés de gros et de détail afin de tenir compte des différences dans les pratiques commerciales. Les données sont limités aux flux en circulation, aucune information permettant d'identifier les commerçants n'est renseignée.

Étant donné que les légumes sont vendus selon des unités de transaction hétérogènes (par exemple paniers, caisses, bottes, poignée), des unités de vente représentatives ont été pesées au cours de l’enquête afin de convertir les prix observés et les dépenses déclarées en équivalents standardisés en kilogrammes. Pour chaque produit, plusieurs unités de vente ont été pesées auprès de différents vendeurs afin d’estimer le poids moyen de l’unité de transaction utilisée sur le marché. Ces mesures ont ensuite été utilisées pour calculer les quantités et les prix exprimés au kilogramme.

## Méthodes de traitement des données :

Les questionnaires complétés ont été codés puis saisis dans une base de données structurée à l’aide d’un modèle de saisie standardisé. Les procédures de nettoyage des données ont inclus la vérification des noms de produits, des unités de vente et de la cohérence des prix entre observations, avant la constitution du jeu de données final.

# APERCU DES DONNEES ET FICHIERS

Le jeu de données inclue un fichier csv pour l'enquête aux détaillants (dt_produce_flows_retail_market.csv), et un deuxième pour l'enquête aux grossistes (dt_produce_flows_wholesale_market.csv).

# INFORMATIONS SPECIFIQUES AUX DONNEES POUR : dt_produce_flows_retail_market.csv

season
-- Nom complet : Saison de collecte
-- Description : Indique la période saisonnière durant laquelle les données ont été collectées
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : ss (saison sèche), sp (saison des pluies)
-- Format : chaîne de caractères

code_obs
-- Nom complet : Code d’identification de l’observation
-- Description : Identifiant unique attribué à chaque observation dans la base de données
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : code numérique unique
-- Format : numérique

type_marche
-- Nom complet : Type de marché
-- Description : Indique si le marché est de gros ou de détail
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : Detail (marché de détail), Gros (marché de gros)
-- Format : chaîne de caractères

nom_marche
-- Nom complet : Nom du marché
-- Description : Nom du marché dans lequel l’enquête a été réalisée
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

fonction_enquete
-- Nom complet : Fonction du répondant
-- Description : Rôle ou activité du répondant au sein du marché (ex. : vendeur, grossiste)
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

sexe_enquete
-- Nom complet : Sexe du répondant
-- Description : Genre du répondant
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : Male, Female
-- Format : chaîne de caractères

type_loc
-- Nom complet : Type d’emplacement de vente
-- Description : Décrit l’espace ou le support utilisé pour exposer le produit sur le marché (ex. : table, sol)
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

type_produit
-- Nom complet : Type de produit (légume)
-- Description : Nom du légume commercialisé
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : liste des légumes étudiés
-- Format : chaîne de caractères

origine_produit_site
-- Nom complet : Site de production
-- Description : Localité précise d’origine du produit
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

origine_produit_region
-- Nom complet : Région de production
-- Description : Région géographique d’origine du produit
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

type_lieu_achat
-- Nom complet : Type de lieu d’approvisionnement
-- Description : Catégorie du lieu où le produit a été acheté
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

nom_lieu_achat
-- Nom complet : Nom du lieu d’approvisionnement
-- Description : Nom spécifique du lieu où le produit a été acheté
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

type_fournisseur
-- Nom complet : Type de fournisseur
-- Description : Fonction ou rôle de l’acteur auprès duquel le produit a été acheté dans la chaîne d’approvisionnement
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre (ex. : producteur, grossiste, intermédiaire)
-- Format : chaîne de caractères

depense_achat_f_cfa
-- Nom complet : Dépense d’achat en FCFA
-- Description : Montant dépensé par le commerçant pour l’achat des produits vendus le jour de l’enquête
-- Unité : FCFA
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

unite_de_transaction
-- Nom complet : Unité de transaction
-- Description : Unité de vente observée utilisée pour commercialiser le produit
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : Botte, Seau, Tas, Planche, Pièce, Sac, Caisse
-- Format : chaîne de caractères

prix_moyen_kg
-- Nom complet : Prix moyen de vente au kilogramme
-- Description : Prix moyen par kilogramme calculé à partir des prix observés et du poids mesuré des unités de transaction
-- Unité : FCFA/kg
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

volume_kg
-- Nom complet : Volume en kilogrammes
-- Description : Volume estimé des produits vendus le jour de l’enquête (depense d’achat / prix moyen au kg)
-- Unité : kg
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

# INFORMATIONS SPECIFIQUES AUX DONNEES POUR : dt_produce_flows_wholesale_market.csv

season
-- Nom complet : Saison de collecte
-- Description : Indique la période saisonnière durant laquelle les données ont été collectées
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : ss (saison sèche), sp (saison des pluies)
-- Format : chaîne de caractères

nom_marche
-- Nom complet : Nom du marché
-- Description : Nom du marché dans lequel l’observation a été réalisée
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

type_produit
-- Nom complet : Type de produit (légume)
-- Description : Nom du légume observé
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : liste des légumes étudiés
-- Format : chaîne de caractères

unite_de_transaction_vente
-- Nom complet : Unité de transaction
-- Description : Unité de vente observée utilisée pour commercialiser le produit
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : Botte (bundle), Seau (bucket), Tas (pile), Planche (bed of crops still in the field), Pièce (piece), Sac (bag), Caisse (crate/box)
-- Format : chaîne de caractères

poids_kg
-- Nom complet : Poids de l’unité de transaction
-- Description : Poids observé des unités de transaction en kilogrammes (ex. : une caisse de tomates au marché de Kibeliba pèse 48 kg)
-- Unité : kg
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

nb_unite
-- Nom complet : Nombre d’unités de transaction
-- Description : Nombre d’unités de transaction observées le jour de l’enquête (ex. : 7 caisses de tomates au marché de Kibeliba)
-- Unité : Non applicable
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques entières positives
-- Format : numérique

prix_ut
-- Nom complet : Prix par unité de transaction
-- Description : Prix de vente observé de chaque unité de transaction le jour de l’enquête (ex. : chaque caisse de tomates au marché de Kibeliba est vendue 18 000 FCFA)
-- Unité : FCFA/unité
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

valeur_total_f_cfa
-- Nom complet : Valeur totale en FCFA
-- Description : Valeur totale des flux commercialisés par produit, estimée à partir du nombre d’unités observées et du prix par unité (nombre_d’unités × prix_par_unité)
-- Unité : FCFA
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

volume_total_kg
-- Nom complet : Volume total en kilogrammes
-- Description : Volume total des flux commercialisés par produit, estimé à partir du nombre d’unités observées et du poids de l’unité de transaction (poids_unité × nombre_d’unités)
-- Unité : kg
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques positives
-- Format : numérique

nb_grossistes
-- Nom complet : Nombre de grossistes
-- Description : Nombre de grossistes présents sur le marché pour un produit donné le jour de l’enquête
-- Unité : Non applicable
-- Séparateur décimal : point
-- Valeurs autorisées : valeurs numériques entières positives
-- Format : numérique

origine_produit
-- Nom complet : Origine du produit
-- Description : Origine du produit telle que déclarée par les grossistes le jour de l’enquête
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

origine_produit_2
-- Nom complet : Origine secondaire du produit
-- Description : Origine secondaire du produit déclarée par les grossistes, si applicable
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

origine_produit_3
-- Nom complet : Origine additionnelle du produit 3
-- Description : Troisième origine du produit déclarée par les grossistes, si applicable
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères

origine_produit_4
-- Nom complet : Origine additionnelle du produit 4
-- Description : Quatrième origine du produit déclarée par les grossistes, si applicable
-- Unité : Non applicable
-- Séparateur décimal : Non applicable
-- Valeurs autorisées : texte libre
-- Format : chaîne de caractères	

## Code des valeurs manquantes : 
Valeurs manquantes = "NA"

## Informations additionnelles : 
Un dictionnaire des variables est également joint au jeu de données.