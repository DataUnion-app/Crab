import spacy

nlp = spacy.load("en_core_web_lg")  # make sure to use larger package!
nlpde = spacy.load("de_core_news_lg")
import pandas as pd
import random


def clean_text(df):
    names = [nlp for nlp in df['nlp_list'].to_numpy().flatten().tolist() if len(nlp) != 0][0]
    names_clean = [x for x in names if str(x) != 'nan']
    names_clean = [sub.replace('\xa0', ' ') for sub in names_clean]
    names_clean = [sub.replace('\x80\x93', ' ') for sub in names_clean]
    names_clean = [sub.replace("\\", "") for sub in names_clean]

    return names_clean


def get_similarities(names_clean, reference, reference_en, nlp, language):
    similarities = []
    for n, i in enumerate(reference):
        doci = nlp(i)

        for j in names_clean:
            docj = nlp(j)
            simil_temp = doci.similarity(docj)
            temp_json = {
                "Language": language,
                "Category": reference_en[n],
                "Text": j,
                "Similarity score": simil_temp
            }
            similarities.append(temp_json)

    return similarities


def get_all_similarities(names_clean, en_reference, de_reference, nlp, nlpde):
    en_ = get_similarities(names_clean, en_reference, en_reference, nlp, 'EN')
    de_ = get_similarities(names_clean, de_reference, en_reference, nlpde, 'DE')

    df_spacy = pd.DataFrame(en_ + de_)
    # filter for similarity scores > 0.1
    df_spacy = df_spacy[df_spacy['Similarity score'] > 0.32]
    agg_functions = ['count', 'mean', 'median', 'max', 'min', 'std']
    final = pd.DataFrame(df_spacy.groupby(['Category'])['Similarity score'].agg(agg_functions).reset_index())
    return final


def compute_profile(df, user):
    # https://www.mbaskool.com/business-concepts/marketing-and-strategy-terms/10821-aio-activities-interests-and-opinions.html#:~:text=AIO%20or%20Activities%2C%20Interests%20and,customer's%20activities%2C%20interests%20and%20opinions.

    AIO_vector = ['Work', 'Hobbies', 'Social Events', 'Vacations', 'Entertainment', 'Club Membership', 'Community', \
                  'Family', 'Home', 'Job', 'Community', 'Recreation', 'Fashion', 'Food', \
                  'Themselves', 'Social Issues', 'Politics', 'Business', 'Economics', 'Education', 'Products']

    attributes = ["conservative", "sporty", "modern", "old", "young", "baby", "chubby", "business dude", "doctor", \
                  "scientist", "astronaut", "cyborg", "hippie", "hip hop", "rock 'n' roll", "painter", "happy", \
                  "curious", "hero"]

    items = ["Golf club", "Tennis racket", "Baseball bat", "Sword", "Laptop", "Phone", "Headphones", "Guitar", \
             "Microphone", "Camera", "nerd glasses", "top hat", "cowboy hat", "flowers"]

    animals = ["Wolf", "Lion", "Owl", "Bear", "Gorilla", "Sloth", "Rabbit", "Fox"]

    AIO_vector_de = ['Arbeit', 'Hobbies', 'Gesellschaftliche Veranstaltungen', 'Urlaub', 'Unterhaltung',
                     'Clubmitgliedschaft', 'Gemeinschaft', \
                     'Familie', 'Zuhause', 'Job', 'Gemeinschaft', 'Erholung', 'Mode', 'Essen', \
                     'Selbst', 'Soziales', 'Politik', 'Wirtschaft', 'Wirtschaft', 'Bildung', 'Produkte']

    attributes_de = ["konservativ", "sportlich", "modern", "alt", "jung", "Baby", "mollig", "Geschäftsmann", "Doktor", \
                     "Wissenschaftler", "Astronaut", "Cyborg", "Hippie", "Hip Hop", "Rock 'n' Roll", "Maler",
                     "glücklich", \
                     "neugierig", "Held"]

    items_de = ["Golfschläger", "Tennisschläger", "Baseballschläger", "Schwert", "Laptop", "Telefon", "Kopfhörer",
                "Gitarre", \
                "Mikrofon", "Kamera", "Nerdbrille", "Zylinder", "Cowboyhut", "Blumen"]

    animals_de = ["Wolf", "Löwe", "Eule", "Bär", "Gorilla", "Faultier", "Kaninchen", "Fuchs"]

    reference_en = [",".join([x, y, z]) for x in animals for y in attributes for z in items]

    def get_best_match(df):
        # sort by max scaled max-mean range
        df = df.sort_values(
            ['count', 'std', 'max', 'median', 'mean', 'min'],
            ascending=[False, True, False, False, False, False]).reset_index()
        df['scaled'] = (df['max'] - df['mean']) / df['std']
        category = df[df['max'] > df['max'].mean()].sort_values('scaled', ascending=False).reset_index().Category[0]
        return df, category

    avatar = []
    df_similarities_an = pd.DataFrame()
    df_similarities_att = pd.DataFrame()
    df_similarities_itm = pd.DataFrame()
    has_enough_data = True
    try:
        names_clean = clean_text(df)
        print('... animal')
        df_similarities_an, category = get_best_match(
            get_all_similarities(names_clean, animals, animals_de, nlp, nlpde))
        avatar.append(category)
        print(avatar)

        print('... attribute')
        df_similarities_att, category = get_best_match(
            get_all_similarities(names_clean, attributes, attributes_de, nlp, nlpde))
        avatar.append(category)
        print(avatar)

        print('... item')
        df_similarities_itm, category = get_best_match(get_all_similarities(names_clean, items, items_de, nlp, nlpde))
        avatar.append(category)
        print(avatar)

    except:
        avatar = random.choice(reference_en).split(',')
        has_enough_data = False
        print(avatar)

    user_avatar = {
        'user': user,
        'avatar': avatar,
        'has_enough_data': has_enough_data
    }

    print('.. Done!')

    return user_avatar, df_similarities_an, df_similarities_att, df_similarities_itm
