# Crab
Backend for DataUnion.app

# Setup

## Build and run using docker image

### Start coudchdb instance

1. Run the command:

`docker run --name crab-couchdb -v ~/couchdb/data:/opt/couchdb/data -e COUCHDB_USER=<username> -e COUCHDB_PASSWORD=<password> -d couchdb:3`
2. Create databases: `users`, `sessions`, `metadata` and update the `properties.ini` file accordingly which will be used to build the docker container below.

### Build the docker container for backend
1. Clone the repository.
2. Copy `sample.ini` to `properties.ini`.
3. Change the properties as needed.
4. Build image: `docker build . -t crab`
5. Run image: `docker run -p 8080:8080 -v data:/data crab`

## Local setup for development

### Couchdb installation

Please follow the installation guide [here](https://docs.couchdb.org/en/stable/install/index.html).

### Starting the backend
1. Install `Python 3.9.0`
2. Navigate to the directory where Crab is cloned.

        `cd *address of this repo on your PC*`
        
3. Optional - 
    
    a. Create a virtual env
        
        `python3 -m venv env`
        
    b. Start a virtual env:

        Linux : `source env/bin/activate`
        Windows: `.\env\Scripts\activate`
        
3. Install dependencies
    Windows: `pip install -r requirements/dev_windows.txt`
    Linux: `pip install -r requirements/prod_linux.txt`
    

4. Copy `sample.ini` and create `properties.ini` file.

5. Start the server `python app.py`

# Helper scripts

### Obtain access token
`python -m helpers.login [--login or --register]`

### Load dummy data

`python helpers.load_dummy_data`

# Supported api

| Method | Endpoint             | Example Usage                                                                                                                                                                                                                                     |
|--------|----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| POST   | /api/v1/upload       | `curl --location --request POST 'http://localhost:8080/api/v1/upload' \ --header 'Content-Type: application/json' \ --data-raw '{    "photo_id" : "XSUdXxoxFF",    "timestamp" : "timestamp",    "other" : "other",    "tags" : ["tag1,tag2"] }'` |
| POST   | /api/v1/upload-file  | `curl --location --request POST 'http://localhost:8080/api/v1/upload-file' \ --form 'file=@"/C:<path>"' \ --form 'uploaded_by="0x123"'`                                                                                                           |
| POST   | /api/v1/upload-zip   | `curl --location --request POST 'http://localhost:8080/api/v1/upload-file' \ --form 'file=@"/C:<path>"' \ --form 'uploaded_by="0x123"'`                                                                                                           |
| GET    | /api/get/my-metadata | `curl --location --request GET 'http://localhost:8080/api/v1/all-metadata'`                                                                                                                                                                       |
| GET    | /api/v1/my-images    | `curl --location --request GET 'http://localhost:8080/api/v1/metadata?eth_address=0x123'`                                                                                                                                                         |
| GET    | /api/v1/get-image-by-id    | `curl --location --request GET 'http://localhost:8080/api/v1/get_image?id=EaglPwWTXM'`                                                                                                                                                            |
| GET    | /api/v1/report-images    | `curl --location --request GET 'http://localhost:8080/api/v1/get_image?id=EaglPwWTXM'`                                                                                                                                                            |
| GET    | /api/vi/stats        | `curl --location --request GET 'http://localhost:8080/api/v1/stats'`                                                                                                                                                                              |

# Troubleshooting

1. If on windows machine and while installing `couchdb` if you see this error, please make sure [dot net 3.5 framework](https://www.microsoft.com/en-in/download/details.aspx?id=21) is installed.
