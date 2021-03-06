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

### Prerequisites

For windows install [Visual studio build tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

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

Please visit the wiki page [here](https://github.com/DataUnion-app/Crab/wiki/Crab-backend-API).
# Troubleshooting

1. If on windows machine and while installing `couchdb` if you see this error, please make sure [dot net 3.5 framework](https://www.microsoft.com/en-in/download/details.aspx?id=21) is installed.


# 🏛 License
```text
Copyright 2021 DataUnion.app
See the LICENSE file for the license of this code.
```
