# Crab
Backend for DataUnion.app

# Setup

## Couchdb installation

Please follow the installation guide [here](https://docs.couchdb.org/en/stable/install/index.html).

## Starting the backend
1. Install `Python 3.9.0`
2. Optional - 

    a. Navigate to the directory where Crab is cloned.
    
        `cd *address of this repo on your PC*`
    
    b. Create a virtual env
        
        `python3 -m venv env`
        
    c. Start a virtual env:

        Linux : `source env/bin/activate`
        Windows: `.\env\Scripts\activate`
        
3. Install dependencies

    `pip install -r requirements.txt`
    
4. Copy `sample.ini` and create `properties.ini` file.

5. Start the server `python app.py`

# Supported api

| Method | Endpoint             | Example Usage                                                                                                                                                                                                                                                                           |
|--------|----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| POST   | /api/v1/upload       | `curl --location --request POST 'http://localhost:8080/api/v1/upload' \ --header 'Content-Type: application/json' \ --data-raw '{    "uploaded_by" : "0x",    "timestamp" : "timestamp",    "other" : "other",    "photo" : "hash",    "tags" : ["t1"] }'`                              |
| POST   | /api/v1/upload-file  | `curl --location --request POST 'http://localhost:8080/api/v1/upload-file' \ --form 'file=@"/C:/Users/Akshay/Desktop/Pic2.jpg"' \ --form 'uploaded_by="flask"' \ --form 'tags="t1,t2,t3"' \ --form 'photo="photo_hash"' \ --form 'other="other-data"' \ --form 'timestamp="timestamp"'` |
| GET    | /api/v1/all-metadata | `curl --location --request GET 'http://localhost:8080/api/v1/all-metadata'`                                                                                                                                                                                                             |
| GET    | /api/v1/metadata     | `curl --location --request GET 'http://localhost:8080/api/v1/metadata?eth_address=0x123'`                                                                                                                                                                                               |
| GET    | /api/v1/get_image    | `curl --location --request GET 'http://localhost:8080/api/v1/get_image?id=EaglPwWTXM'`                                                                                                                                                                                                  |

# Troubleshooting

1. If on windows machine and while installing `couchdb` if you see this error, please make sure [dot net 3.5 framework](https://www.microsoft.com/en-in/download/details.aspx?id=21) is installed.
