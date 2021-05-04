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

- **GET** `/api/v1/stats`
  - Parameters:
    - start_time
    - end_time

  - Example:
    ```bash
    curl --location --request GET 'http://localhost:8080/api/v1/stats?start_time=1&end_time=1719175642097'
    ```  
  - Response:
    ```JSON
    {
      "result": {
          "data": [
              {
                  "num_images": 10,
                  "tags": [
                      {
                          "name": "tag4",
                          "value": 10
                      },
                      {
                          "name": "fluctuability",
                          "value": 1
                      },
                      {
                          "name": "telestereoscope",
                          "value": 1
                      }
                  ],
                  "time": 1620086400.0
              }
          ],
          "initial_images": 10
      },
      "status": "success"
    }
    ```

- **GET** `/api/v1/stats/summary/tags`
  - Parameters:
    - None
  - Example:
    ```bash
    curl --location --request GET 'http://localhost:8080/api/v1/stats/tags'
    ```  
  - Response:
    ```JSON
     {
      "result": {
          "desc_down_votes": 0,
          "desc_up_votes": 0,
          "tags_down_votes": 0,
          "tags_up_votes": 0
      },
      "status": "success"
    }
    ```

- **GET** `/api/v1/stats/summary/summary/user`
  - Parameters:
    - None
  - Example:
    ```bash
    curl --location --request GET 'http://localhost:8080/api/v1/stats/user-tags --header 'Authorization: Bearer <access_token>'
    ```  
  - Response:
    ```JSON
    {
    "result": {
      "total_description_down_votes": 0,
      "total_description_up_votes": 0,
      "total_images_verified": 0,
      "total_tag_down_votes": 0,
      "total_tag_up_votes": 0
    },
    "status": "success"
    }
    ```

- **GET** `/api/v1/stats/user-tag-count`
  - Parameters:
    - start_time
    - end_time
  - Example:
    ```bash
    curl --location --request GET 'http://localhost:8080/api/v1/stats/user-tag-count?start_time=0&end_time=1700000000000' --header 'Authorization: Bearer <access_token>'
    ```
  - Response:
    ```
    {
      "result": [
          {
              "descriptions_down_votes": 1,
              "descriptions_up_votes": 0,
              "tags_down_votes": 1,
              "tags_up_votes": 1,
              "time": 1620086400.0
          }
      ],
      "status": "success"
    }
    ```
    
- **GET** `/api/v1/stats/user-stats`
  - Parameters:
    - start_time
    - end_time
  - Example:
    ```bash
    curl --location --request GET 'http://localhost:8080/api/v1/stats/user-stats?start_time=1619641680&end_time=1619641690&interval=24' --header 'Authorization: Bearer <access_token>'
    ```
  - Response:
    ```JSON
    {
        "result": [],
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



