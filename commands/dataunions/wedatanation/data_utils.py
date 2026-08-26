"""Extract nested values from a JSON tree."""
import pandas as pd


def json_extract(obj, key):
    """Recursively fetch values from nested JSON."""
    arr = []

    def extract(obj, arr, key):
        """Recursively search for values of key in JSON tree."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    extract(v, arr, key)
                elif k == key:
                    arr.append(v)
        elif isinstance(obj, list):
            for item in obj:
                extract(item, arr, key)
        return arr

    values = extract(obj, arr, key)
    return values


def get_users_list(connection):
    query = {
        'selector': {
            'type': 'json',
        },
        'fields': [
            "uploaded_by",
        ]}
    dat = pd.json_normalize(connection.query_data(query)['result']).drop_duplicates().uploaded_by.tolist()
    return (dat)


def get_docs_by_user(connection, user_id):
    query = {
        'selector': {
            'uploaded_by': user_id,
            'type': 'json'
        },
        'fields': [
            "uploaded_by",
            "json_entity_type",
            "_id",
            "raw"
        ]}
    dat = pd.json_normalize(connection.query_data(query)['result'], max_level=0)
    dat = dat.where(dat.astype(bool), 0)
    dat = dat.loc[dat.raw != 0, :]
    dat = dat.drop(['raw'], axis=1)

    return (dat)


def get_query_names(_id, json_entity_type, connection, max_level):
    query = {
        'selector': {
            '_id': _id,
            'json_entity_type': json_entity_type,
            'type': 'json',
        },
        'fields': [
            "_id",
            "uploaded_by",
            "raw"
        ]}

    dat = connection.query_data(query)['result']
    cols = pd.json_normalize(dat, max_level=max_level).columns.values[2:]
    user = dat[0]['uploaded_by']
    return cols, user


def query_sub_sections(_id, json_entity_type, connection, section, keys):
    query = {
        'selector': {
            '_id': _id,  # 'bIQDusRslZLktGn'
            'json_entity_type': json_entity_type,  # 'facebook'
            'type': 'json',
        },
        'fields': [
            "_id",
            "uploaded_by",
            section
        ]}
    dat = connection.query_data(query)['result']

    extracted_dat = []
    if (section.split('.')[-1] == 'ads_interests'):
        extracted_dat = pd.json_normalize(dat).iloc[:, -1][0]
    else:
        for k in keys:
            extracted_dat = extracted_dat + json_extract(dat, k)

    if (len(extracted_dat) > 0):
        extracted_dat = list(filter(None, extracted_dat))
        extracted_dat = [x for x in extracted_dat if str(x) != 'nan']
    #        extracted_dat = [sub.replace('\xa0',' ') for sub in extracted_dat]
    #        extracted_dat = [sub.replace('\x80\x93',' ') for sub in extracted_dat]
    #        extracted_dat = [sub.replace('\x80',' ') for sub in extracted_dat]
    #        extracted_dat = [sub.replace("\\","") for sub in extracted_dat]

    return (extracted_dat)


def create_profile_table(_id, json_entity_type, connection, max_level, keys):
    final_data = []
    query_names, user = get_query_names(_id, json_entity_type, connection, max_level)
    for q in query_names:
        nlp_list = query_sub_sections(_id, json_entity_type, connection, q, keys)

        temp_dict = {
            'user': user,
            '_id': _id,
            'json_entity_type': json_entity_type,
            'title': q.split('.')[-1],
            'nlp_list': nlp_list,
            'objects_counts': len(nlp_list),
        }

        final_data.append(temp_dict)

    return final_data


def process_fb_data(_id, connection):
    keys = ['name', 'description', 'title', 'text', 'comment', 'reaction', 'value', 'advertiser_name', "0", "OrderId",
            "TitleName", "TitleDescription"]
    df = create_profile_table(_id, 'facebook', connection, 3, keys)

    return df


def process_amazon_data(_id, connection):
    query = {
        'selector': {
            '_id': _id,
            "json_entity_type": 'amazon',
            'type': 'json',
        },
        'fields': [
            "_id",
            "uploaded_by",
            "raw.Amazon"
        ]}

    dat = connection.query_data(query)['result']

    final_data = []
    query_names, user = get_query_names(_id, 'amazon', connection, 3)
    video_descriptions = list(dat[0]['raw']['Amazon']['PrimeVideo.WatchEvent.2.1']['1']['TitleDescription'].values())
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'amazon',
        'title': 'video_descriptions',
        'nlp_list': video_descriptions,
        'objects_counts': len(video_descriptions),
    }
    final_data.append(temp_dict)
    audible_titles = list(dat[0]['raw']['Amazon']['Audible.CartHistory']['CartHistory']['Title'].values())
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'amazon',
        'title': 'audible_titles',
        'nlp_list': audible_titles,
        'objects_counts': len(audible_titles),
    }
    final_data.append(temp_dict)

    return final_data


def process_netflix_data(_id, connection):
    query = {
        'selector': {
            '_id': _id,
            "json_entity_type": 'netflix',
            'type': 'json',
        },
        'fields': [
            "_id",
            "uploaded_by",
            "raw"
        ]}

    dat = connection.query_data(query)['result']

    final_data = []
    query_names, user = get_query_names(_id, 'netflix', connection, 3)

    try:
        l = list(dat[0]["raw"]["MESSAGES"]["MessagesSentByNetflix"]["Title Name"].values())
        l = list(filter(lambda v: v is not None, l))
        temp_dict = {
            'user': user,
            '_id': _id,
            'json_entity_type': 'netflix',
            'title': 'title_names',
            'nlp_list': l,
            'objects_counts': len(l),
        }
        final_data.append(temp_dict)
        l_unique = list(set(l))
        temp_dict = {
            'user': user,
            '_id': _id,
            'json_entity_type': 'netflix',
            'title': 'unique_title_names',
            'nlp_list': l_unique,
            'objects_counts': len(l_unique),
        }
        final_data.append(temp_dict)
    except:
        pass

    return final_data


def process_zalando_data(_id, connection):
    query = {
        'selector': {
            '_id': _id,
            "json_entity_type": 'zalando',
            'type': 'json',
        },
        'fields': [
            "_id",
            "uploaded_by",
            "raw"
        ]}

    dat = connection.query_data(query)['result']

    final_data = []
    query_names, user = get_query_names(_id, 'zalando', connection, 3)

    l = list(dat[0]["raw"]["Zalando"]["Customer_Data_Extract_wishlist"]["Brand"].values())
    l = list(filter(lambda v: v is not None, l))
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'zalando',
        'title': 'wished_brands',
        'nlp_list': l,
        'objects_counts': len(l),
    }
    final_data.append(temp_dict)
    l_unique = list(set(l))
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'zalando',
        'title': 'unique_wished_brands',
        'nlp_list': l_unique,
        'objects_counts': len(l_unique),
    }
    final_data.append(temp_dict)

    bought = list(dat[0]["raw"]["Zalando"]["Customer_Data_Extract_article"]["Brand"].values())
    bought = list(filter(lambda v: v is not None, bought))
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'zalando',
        'title': 'bought_brands',
        'nlp_list': bought,
        'objects_counts': len(bought),
    }
    final_data.append(temp_dict)
    bought_unique = list(set(bought))
    temp_dict = {
        'user': user,
        '_id': _id,
        'json_entity_type': 'zalando',
        'title': 'unique_bought_brands',
        'nlp_list': bought_unique,
        'objects_counts': len(bought_unique),
    }
    final_data.append(temp_dict)

    return final_data


def process_spotify_data(_id, connection):
    keys = ['artist', 'album', 'track', 'name', 'show', 'trackName', 'artistName', 'albumName', 'showName', 'rating',
            'searchQuery']
    df = create_profile_table(_id, 'spotify', connection, 3, keys)

    return df


def unified_profile_data(user_id, connection):
    user_docs = get_docs_by_user(connection, user_id)

    final = []
    docs = user_docs['_id'].tolist()
    platform = user_docs['json_entity_type'].tolist()
    for i, doc in enumerate(docs):
        if (platform[i] == 'facebook'):
            try:
                final = final + process_fb_data(doc, connection)
            except:
                pass
        elif (platform[i] == 'amazon'):
            try:
                final = final + process_amazon_data(doc, connection)
            except:
                pass
        elif (platform[i] == 'netflix'):
            try:
                final = final + process_netflix_data(doc, connection)
            except:
                pass
        elif (platform[i] == 'zalando'):
            try:
                final = final + process_zalando_data(doc, connection)
            except:
                pass
        elif (platform[i] == 'spotify'):
            try:
                final = final + process_spotify_data(doc, connection)
            except:
                pass
        else:
            try:
                final = final
            except:
                pass

    return final
