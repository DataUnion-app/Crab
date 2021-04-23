# Crab documentation

Supported HTTP REST apis

## Authentication


- /login
  - method: POST
  - body:
```

{
    "public_address": "0x0C82d6217153F58adB9C8350D9E148Fce978BF47",
    "signature": "<signature>"
}

```

- /logout
- /get-nonce
    - method: GET
    - e.g. `http://localhost:8080/get-nonce?public_address=<public_address>

- /register
    - method: POST
    - body:
```

{
    "public_address" : "<public_address>"
}

```
- /refresh

- /revoke-refresh-token

- /check

## Metadata


- /api/v1/upload

  - method: POST
  - Authorziation header (required): Bearer token
  - body parameters
      - timestamp
      - tags
      - photo_id
      - other
      - description (optional)

  - Response:
    ```JSON
    {"status": "success"}
    ```

- /api/v1/upload-file

  - method: POST


- **POST** `/api/v1/bulk/upload-zip`

  - method: POST

- **GET** `/api/get/my-metadata`
    - Response:
    ```
        {
            "page": 1,
            "page_size": 100,
            "result": [
                {
                    "_id": "cimHzaQSxK",
                    "tag_data": [
                        {
                            "created_at": 1611057900.844088,
                            "other": {
                                "description": "sample text"
                            },
                            "tags": [
                                "t1,ty"
                            ],
                            "updated_at": 1611057900.844088,
                            "uploaded_by": "0x60E41b9d32Ef84a85fd9D28D88c57B4EEd730eDa"
                        }
                    ]
                }
            ]
        }
    ```

- /api/v1/my-images

  - method: GET

  - Authorziation header (required): Bearer token

  - parameters:
      - page: (optional) This is a number.

  - response
      - 200
        
           .. code-block:: JSON
``` 
           {
               "page": 1, "page_size": 100,
               "result": [
                 {
                  "filename": "bf7ffffe72f00000-img5.PNG",
                  "hash": "bf7ffffe72f00000",
                  "type": "image",
                  "uploaded_at": 1612003116.712261
                 }
                ]
            }
```

- /api/v1/get-image-by-id

  - method: GET

  - parameters:
        - id : Required. This is the image id.

  - response
        - 200
        Image

- /api/v1/report-images

  - method: POST

  - Authorziation header (required): Bearer token

  - parameters:
      - photos: (required) This is the list of json objects e.g. ```[{"photo_id": image_id}]```.
   
  body e.g. {'photos': [{'photo_id': 'abc'}]}

  - response
      - 200
        
           .. code-block:: JSON
``` 
           {"status": "success"}
```

- /api/v1/verify-images

  - method: POST

  - Authorziation header (required): Bearer token

  - body:
      - data: (required) 
      - e.g.
        ```
        {
            "data" :[
                {
                    "image_id" :"fdf7c301000181e8",
                    "tags":{
                        "up_votes":["test"],
                        "down_votes":[]
                    },
                    "descriptions":{
                        "up_votes":["test_Description 1"],
                        "down_votes":["test_Description 2"]
                    }
                }
            ]
        }
    ```

  - Response:
      - 200
        ```JSON 
            {"status": "success"}
        ```

***

## Stats

- **GET** `/api/vi/my-stats`
  - Parameters:
      - None
  - Example:
    ```bash
    curl --location --request GET 'https://<hostname>/api/v1/my-stats' --header 'Authorization: Bearer <token>'
    ```
  - Response:
    ```
           {
            "result": {[
            {
              "num_images": 13,
              "time": 1614124800000
            },
            {
              "num_images": 0,
              "time": 1614128400000
            },
            {
              "num_images": 0,
              "time": 1614132000000
            }...
            ],
            "status": "success"
               }
    ```

- **GET** `/api/v1/my-tag-stats`
  - Parameters:
    - None
  - Example:
    ```bash
    curl --location --request GET 'https://<hostname>/api/v1/my-tag-stats' --header 'Authorization: Bearer <token>'
    ```
  - Response:
    ```JSON
    {
        "result": {
            "total_description_down_votes": 2,
            "total_description_up_votes": 0,
            "total_images": 2,
            "total_tag_down_votes": 2,
            "total_tag_up_votes": 1
        },
        "status": "success"
    }
    ```

***

## Staticdata

- /staticdata/tags

  - method: GET

  - parameters:
      - type (required)
             RECOMMENDED_WORDS or BANNED_WORDS
- /staticdata/user-count
   
  - method: GET
  - parameters: None



