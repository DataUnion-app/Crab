# Crab documentation

Supported HTTP REST apis

## Authentication

- /login
    - method: POST
    - body:
  ```JSON
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
    ```JSON
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
        ```JSON
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

    - response - 200 Image

- /api/v1/report-images

    - method: POST

    - Authorziation header (required): Bearer token

    - parameters:
        - photos: (required) This is the list of json objects e.g. ```[{"photo_id": image_id}]```.

  body e.g. {'photos': [{'photo_id': 'abc'}]}

    - response
        - 200
        ```JSON
        {"status": "success"}
        ```

- /api/v1/verify-image

    - method: POST

    - Authorziation header (required): Bearer token

    - body:
        - data: (required)
        - e.g.
          ```JSON
          {
            "image_id" :"6404e078ddb331f2",
            "verification" :{
              "tags":{
                  "up_votes":["t1"],
                  "down_votes":["my own down vote"]
              },
            "descriptions":{
                  "up_votes":[],
                  "down_votes":["test_sDescription 2"]
              }  
            },
            "annotation" :{
              "tags":["tag1","tag2"],
              "description":"sample text"
            }
          }
          ```

    - Response:
        - 200
          ```JSON 
              {"status": "success"}
          ```

***

## Stats



- **GET** `/api/v1/stats/user`
    - Parameters:
        - start_date: Date in 'dd-mm-yyyy' format
        - end_date: Date in 'dd-mm-yyyy' format
    - Example:
      ```bash
        curl --location --request GET 'http://localhost:8080/api/v1/stats/user?start_date=01-01-2018&end_date=06-06-2021' --header 'Authorization: Bearer <access_token>'
      ```
    - Response:
        - 200
        ```JSON
           {
            "result": {
                "tag_annotations": [
                    {
                        "date": "6-5-2021",
                        "value": 18
                    }
                ],
                "text_annotations": [
                    {
                        "date": "6-5-2021",
                        "value": 5
                    }
                ],
                "uploads": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "verifications": [
                    {
                        "date": "6-5-2021",
                        "value": 6
                    }
                ]
            },
            "status": "success"
        }
        ```

- **GET** `/api/v1/stats/overall`
    - Parameters:
        - start_date: Date in 'dd-mm-yyyy' format
        - end_date: Date in 'dd-mm-yyyy' format
    - Example:
      ```bash
        curl --location --request GET 'http://localhost:8080/api/v1/stats/overall?start_date=01-01-2018&end_date=06-06-2021''
      ```
    - Response:
        - 200
        ```JSON
           {
            "result": {
                "tag_annotations": [
                    {
                        "date": "6-5-2021",
                        "value": 18
                    }
                ],
                "text_annotations": [
                    {
                        "date": "6-5-2021",
                        "value": 5
                    }
                ],
                "uploads": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "verifications": [
                    {
                        "date": "6-5-2021",
                        "value": 6
                    }
                ]
            },
            "status": "success"
        }
        ```


- **GET** `/api/v1/stats/overall-tags`
    - Parameters:
        - start_date: Date in 'dd-mm-yyyy' format
        - end_date: Date in 'dd-mm-yyyy' format
    - Example:
      ```bash
        curl --location --request GET 'http://localhost:8080/api/v1/stats/-tags?start_date=01-01-2018&end_date=06-06-2021''
      ```
    - Response:
        - 200
        ```JSON
        {
            "result": {
                "bronchocele": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "gallantize": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "pennywinkle": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "sicca": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ],
                "venomer": [
                    {
                        "date": "6-5-2021",
                        "value": 1
                    }
                ]
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



