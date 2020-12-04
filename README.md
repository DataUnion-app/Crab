# Crab
Backend for DataUnion.app

# Setup

## Couchdb installation

Please follow the installation guide [here](https://docs.couchdb.org/en/stable/install/index.html).

## Starting the backend
1. Install `Python 3.9.0`
2. Optional - 

    a. Create a virtual env
    
        `python3 -m venv env`
    b. Start a virtual env:

        Linux : `source env/bin/activate`
        Windows: `.\env\Scripts\activate`
3. Install dependencies

    `pip install requirements.txt`
    
4. Copy `sample.ini` and create `properties.ini` file.

5. Start the server `python app.py`

# Supported api

| Method | Endpoint             |
|--------|----------------------|
| GET    | /api/v1/upload       |
| POST   | /api/v1/all-metadata |

# Troubleshooting

1. If on windows machine and while installing `couchdb` if you see this error, please make sure [dot net 3.5 framework](https://www.microsoft.com/en-in/download/details.aspx?id=21) is installed.