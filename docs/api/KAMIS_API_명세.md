# KAMIS 가격정보 API 사용 명세

> 대상 프로젝트: KAMIS 멀티마켓 가격 상관관계 대시보드  
> 확인 기준일: 2026-09-24  
> 공식 문서: https://www.kamis.or.kr/customer/reference/openapi_list.do

## 1. 목적과 사용할 API

KAMIS 전체 품목·품종의 도매가격과 소매가격을 수집하기 위해 다음 3개 API를 사용한다.

| 순서 | API | action | 인증 | 용도 |
|---:|---|---|---|---|
| 1 | 농축수산물 품목 및 등급 코드표 | productInfo | 현재 실제 호출은 인증 없이 가능 | 수집 대상 품목·품종·단위·등급 사전 생성 |
| 2 | 기간별 품목별 도매 가격 | periodWholesaleProductList | 필요 | 품목별 도매가격 수집 및 3년 백필 |
| 3 | 기간별 품목별 소매 가격 | periodRetailProductList | 필요 | 품목별 소매가격 수집 및 3년 백필 |

기존 일별 품목별 도·소매 API보다 기간 설정 API 2종을 우선 사용한다. 공식 안내상 요청 한 번에 설정할 수 있는 기간은 최대 1년이다.

## 2. 공통 설정

### 기본 URL

공식 문서의 예시는 HTTP를 사용하지만 구현에서는 HTTPS를 사용한다.

    https://www.kamis.or.kr/service/price/xml.do

### 인증정보

기간별 가격 API에는 다음 값이 필요하다.

| 이름 | 설명 |
|---|---|
| p_cert_key | KAMIS Open API 인증키 |
| p_cert_id | Open API 신청 시 등록한 요청자 ID |

브라우저 로그인 세션과 API 인증값은 별개다. 로그인된 브라우저의 쿠키를 수집기에 복사하지 않고 발급받은 API 인증값을 사용한다.

인증정보는 소스코드나 CSV에 기록하지 않는다.

    KAMIS_CERT_KEY=발급받은_인증키
    KAMIS_CERT_ID=요청자_ID

권장 환경변수 이름은 KAMIS_CERT_KEY와 KAMIS_CERT_ID다. 커밋 가능한 예제 파일에는 실제 값을 넣지 않는다.

### 반환 형식

| p_returntype | 형식 | 권장 여부 |
|---|---|---|
| json | JSON | 권장 |
| xml | XML | 장애 확인 및 원문 비교용 |

KAMIS 응답의 Content-Type이 text/plain으로 내려올 수 있으므로 Content-Type만으로 파서를 결정하지 말고 요청한 p_returntype을 기준으로 파싱한다.

### 공통 오류 코드

| 코드 | 의미 | 수집기 처리 |
|---|---|---|
| 000 | Success. | 정상 처리 |
| 001 | no data | 정상적인 무자료로 기록하고 재시도하지 않음 |
| 200 | Wrong Parameters. | 요청 파라미터와 코드 매핑을 검증한 뒤 실패 처리 |
| 900 | Unauthenticated request. | 인증키·요청자 ID 확인 후 해당 실행 실패 처리 |

HTTP 200이어도 본문의 오류 코드는 실패일 수 있다. HTTP 상태와 응답 오류 코드를 모두 검사한다.

## 3. 품목·품종·단위·등급 사전

### 요청

| 항목 | 값 |
|---|---|
| action | productInfo |
| p_returntype | json 또는 xml |

JSON 요청 예시:

    GET https://www.kamis.or.kr/service/price/xml.do?action=productInfo&p_returntype=json

XML 요청 예시:

    GET https://www.kamis.or.kr/service/price/xml.do?action=productInfo&p_returntype=xml

2026-09-24 실제 확인 결과, 인증 파라미터 없이 두 요청 모두 HTTP 200과 error_code=000을 반환했다.

### JSON 최상위 구조

    {
      "condition": [[[]]],
      "error_code": "000",
      "info": [
        {
          "itemcategorycode": "100",
          "itemcategoryname": "식량작물",
          "itemcode": "111",
          "itemname": "쌀",
          "kindcode": "01",
          "kindname": "20kg",
          "wholesale_unit": "kg",
          "wholesale_unitsize": "20",
          "retail_unit": "kg",
          "retail_unitsize": "20",
          "eco_unit": [],
          "eco_unitsize": [],
          "whole_productrankcode": "04",
          "retail_productrankcode": "04,05",
          "new_natreu_productrankcode": []
        }
      ]
    }

빈 값이 빈 문자열이 아니라 빈 배열로 반환될 수 있다. 문자열 변환 전에 null, 빈 문자열, 빈 배열을 모두 결측으로 정규화한다.

### info 항목

| 필드 | 의미 | 내부 저장 필드 |
|---|---|---|
| itemcategorycode | 부류코드 | category_code |
| itemcategoryname | 부류명 | category_name |
| itemcode | 품목코드 | item_code |
| itemname | 품목명 | item_name |
| kindcode | 품종코드 | kind_code |
| kindname | 품종명 | variety |
| wholesale_unit | 도매 출하단위 | wholesale_unit |
| wholesale_unitsize | 도매 출하단위 크기 | wholesale_unit_size |
| retail_unit | 소매 출하단위 | retail_unit |
| retail_unitsize | 소매 출하단위 크기 | retail_unit_size |
| eco_unit | 친환경 출하단위 | eco_unit |
| eco_unitsize | 친환경 출하단위 크기 | eco_unit_size |
| whole_productrankcode | 도매 등급코드 | wholesale_rank_codes |
| retail_productrankcode | 소매 등급코드 | retail_rank_codes |
| new_natreu_productrankcode | 친환경 등급코드 | eco_rank_codes |

공식 응답 필드의 whole_productrankcode는 철자가 wholesale이 아닌 whole이다. 원문 키를 그대로 읽고 내부 필드에서 wholesale_rank_codes로 정규화한다.

### 부류코드

| 코드 | 부류 |
|---:|---|
| 100 | 식량작물 |
| 200 | 채소류 |
| 300 | 특용작물 |
| 400 | 과일류 |
| 500 | 축산물 |
| 600 | 수산물 |

부류·품목·품종·등급 조합을 코드로 하드코딩하지 않는다. productInfo 응답을 원본 CSV로 저장한 뒤 가격 API 반복 호출의 기준으로 사용한다.

### 공식 문서 주의사항

15번 공식 상세 페이지의 요청 변수 표에는 p_startday, p_endday 등 기간조회용 변수가 섞여 있고 응답 필드도 일부 중복돼 있다. 그러나 공식 샘플 URL과 2026-09-24 실제 호출에서는 action=productInfo와 p_returntype만으로 정상 응답했다. 구현과 테스트는 실제 응답 구조를 기준으로 하되 공식 문서 변경 여부를 정기적으로 확인한다.

## 4. 기간별 도매가격

공식 상세 문서: https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=16

### 요청 URL

    GET https://www.kamis.or.kr/service/price/xml.do?action=periodWholesaleProductList

### 요청 파라미터

| 파라미터 | 형식 | 설명 | 프로젝트 사용 |
|---|---|---|---|
| p_cert_key | string | 인증키 | 필수 |
| p_cert_id | string | 요청자 ID | 필수 |
| p_returntype | string | json 또는 xml | json |
| p_startday | string | 시작일 | YYYY-MM-DD |
| p_endday | string | 종료일 | YYYY-MM-DD, 시작일로부터 최대 1년 |
| p_countrycode | string | 지역코드, 미지정 시 전체지역 | 기본은 빈 값 |
| p_itemcategorycode | string | 부류코드 | productInfo 값 |
| p_itemcode | string | 품목코드 | productInfo 값 |
| p_kindcode | string | 품종코드 | productInfo 값 |
| p_productrankcode | string | 도매 등급코드 | whole_productrankcode 값 |
| p_convert_kg_yn | string | kg 환산 여부, Y 또는 N | 기본 Y, 개수·마리 품목은 원단위도 함께 검증 |

### 요청 템플릿

    https://www.kamis.or.kr/service/price/xml.do
      ?action=periodWholesaleProductList
      &p_startday={YYYY-MM-DD}
      &p_endday={YYYY-MM-DD}
      &p_itemcategorycode={CATEGORY_CODE}
      &p_itemcode={ITEM_CODE}
      &p_kindcode={KIND_CODE}
      &p_productrankcode={WHOLESALE_RANK_CODE}
      &p_countrycode={COUNTRY_CODE_OR_EMPTY}
      &p_convert_kg_yn=Y
      &p_cert_key={KAMIS_CERT_KEY}
      &p_cert_id={KAMIS_CERT_ID}
      &p_returntype=json

쌀 20kg, 상품, 서울의 형식 예시:

    https://www.kamis.or.kr/service/price/xml.do?action=periodWholesaleProductList&p_startday=2026-09-01&p_endday=2026-09-24&p_itemcategorycode=100&p_itemcode=111&p_kindcode=01&p_productrankcode=04&p_countrycode=1101&p_convert_kg_yn=Y&p_cert_key={KAMIS_CERT_KEY}&p_cert_id={KAMIS_CERT_ID}&p_returntype=json

### 응답 필드

| 필드 | 의미 | 내부 저장 필드 |
|---|---|---|
| condition | 요청 메시지 | request_condition |
| data | 응답 데이터 | 파싱 대상 배열 |
| itemname | 품목명 | item_name |
| kindname | 품종명 | variety |
| countyname | 시군구 | region |
| marketname | 마켓명 | market_name |
| yyyy | 연도 | year |
| regday | 날짜 | observed_date |
| price | 가격 | price_krw |

price는 문자열로 취급해 쉼표와 공백을 제거한 뒤 숫자로 변환한다. 무자료 표시나 비어 있는 값은 0으로 변환하지 않고 결측으로 둔다.

## 5. 기간별 소매가격

공식 상세 문서: https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=17

### 요청 URL

    GET https://www.kamis.or.kr/service/price/xml.do?action=periodRetailProductList

### 요청 파라미터

도매 API와 파라미터 형식은 같고 action과 등급코드 출처가 다르다.

| 파라미터 | 형식 | 설명 | 프로젝트 사용 |
|---|---|---|---|
| p_cert_key | string | 인증키 | 필수 |
| p_cert_id | string | 요청자 ID | 필수 |
| p_returntype | string | json 또는 xml | json |
| p_startday | string | 시작일 | YYYY-MM-DD |
| p_endday | string | 종료일 | YYYY-MM-DD, 시작일로부터 최대 1년 |
| p_countrycode | string | 소매 지역코드, 미지정 시 전체지역 | 기본은 빈 값 |
| p_itemcategorycode | string | 부류코드 | productInfo 값 |
| p_itemcode | string | 품목코드 | productInfo 값 |
| p_kindcode | string | 품종코드 | productInfo 값 |
| p_productrankcode | string | 소매 등급코드 | retail_productrankcode 값 |
| p_convert_kg_yn | string | kg 환산 여부, Y 또는 N | 기본 Y, 원단위도 함께 검증 |

### 요청 템플릿

    https://www.kamis.or.kr/service/price/xml.do
      ?action=periodRetailProductList
      &p_startday={YYYY-MM-DD}
      &p_endday={YYYY-MM-DD}
      &p_itemcategorycode={CATEGORY_CODE}
      &p_itemcode={ITEM_CODE}
      &p_kindcode={KIND_CODE}
      &p_productrankcode={RETAIL_RANK_CODE}
      &p_countrycode={COUNTRY_CODE_OR_EMPTY}
      &p_convert_kg_yn=Y
      &p_cert_key={KAMIS_CERT_KEY}
      &p_cert_id={KAMIS_CERT_ID}
      &p_returntype=json

쌀 20kg, 상품, 서울의 형식 예시:

    https://www.kamis.or.kr/service/price/xml.do?action=periodRetailProductList&p_startday=2026-09-01&p_endday=2026-09-24&p_itemcategorycode=100&p_itemcode=111&p_kindcode=01&p_productrankcode=04&p_countrycode=1101&p_convert_kg_yn=Y&p_cert_key={KAMIS_CERT_KEY}&p_cert_id={KAMIS_CERT_ID}&p_returntype=json

### 응답 필드

condition, data, itemname, kindname, countyname, marketname, yyyy, regday, price를 반환한다. 내부 정규화 규칙은 도매 API와 같고 source와 price_type만 각각 kamis와 retail로 기록한다.

## 6. 지역코드

### 도매가격 지원 지역

| 코드 | 지역 |
|---:|---|
| 1101 | 서울 |
| 2100 | 부산 |
| 2200 | 대구 |
| 2401 | 광주 |
| 2501 | 대전 |

### 소매가격 지원 지역

| 코드 | 지역 | 코드 | 지역 |
|---:|---|---:|---|
| 1101 | 서울 | 2100 | 부산 |
| 2200 | 대구 | 2300 | 인천 |
| 2401 | 광주 | 2501 | 대전 |
| 2601 | 울산 | 2701 | 세종 |
| 3111 | 수원 | 3112 | 성남 |
| 3113 | 의정부 | 3138 | 고양 |
| 3145 | 용인 | 3211 | 춘천 |
| 3214 | 강릉 | 3311 | 청주 |
| 3411 | 천안 | 3511 | 전주 |
| 3613 | 순천 | 3711 | 포항 |
| 3714 | 안동 | 3814 | 창원 |
| 3818 | 김해 | 3911 | 제주 |

전국 비교를 기본값으로 사용할 때는 p_countrycode를 비워 전체지역 응답을 요청한다. 특정 지역 분석은 별도 실행으로 분리한다.

## 7. 등급과 단위 사용 원칙

- 흔히 04는 상품, 05는 중품으로 나타나지만 모든 품목에 동일 조합이 있다고 가정하지 않는다.
- 도매 호출은 productInfo의 whole_productrankcode를 쉼표로 분리해 사용한다.
- 소매 호출은 retail_productrankcode를 쉼표로 분리해 사용한다.
- 등급코드가 빈 배열, 빈 문자열 또는 누락이면 해당 가격 유형의 호출 대상에서 제외하고 사유를 기록한다.
- p_convert_kg_yn=Y 응답과 원 조사단위 N 응답을 초기 검증 단계에서 함께 비교한다.
- 개수·마리·단처럼 중량 환산이 부적절한 품목은 KAMIS가 제공한 원단위를 유지하고 온라인 상품도 같은 단위로 비교한다.

## 8. 수집 순서

### 매일 증분 수집

1. productInfo를 호출해 최신 품목 사전을 raw CSV로 저장한다.
2. 전일 사전과 비교해 신규·변경·삭제 후보를 기록한다.
3. 품목별 도매 등급 조합으로 periodWholesaleProductList를 호출한다.
4. 품목별 소매 등급 조합으로 periodRetailProductList를 호출한다.
5. error_code=001은 무자료로 기록한다.
6. 응답 원문을 보존한 뒤 정규화 CSV를 만든다.
7. 동일 source, price_type, observed_date, 품목·품종·등급·지역·마켓 조합의 중복을 제거한다.

### 과거 3년 백필

기간별 API의 최대 조회기간이 1년이므로 3년을 1년 이하 구간으로 나눈다. 구간 경계 날짜가 겹칠 수 있으므로 저장 후 고유키로 중복 제거한다.

예시:

1. 2023-09-25 ~ 2024-09-24
2. 2024-09-25 ~ 2025-09-24
3. 2025-09-25 ~ 2026-09-24

실제 실행일을 기준으로 날짜를 계산하고 윤년을 고려한다.

## 9. 정규화 스키마

가격 API 결과를 다음 공통 구조로 저장한다.

| 필드 | 설명 |
|---|---|
| run_id | 일일 수집 실행 ID |
| source | kamis |
| price_type | wholesale 또는 retail |
| observed_date | KAMIS 가격 관측일 |
| collected_at | 실제 수집시각, KST |
| category_code | 부류코드 |
| item_code | 품목코드 |
| kind_code | 품종코드 |
| rank_code | 등급코드 |
| item_name | 품목명 |
| variety | 품종명 |
| region | 시군구 |
| market_name | 시장명 |
| price_krw | 원 단위 가격 |
| requested_convert_kg | kg 환산 요청 여부 |
| source_unit | productInfo의 원 출하단위 |
| source_unit_size | productInfo의 원 출하단위 크기 |
| raw_file | 원본 CSV 또는 응답 파일 경로 |

권장 고유키:

    source
    + price_type
    + observed_date
    + category_code
    + item_code
    + kind_code
    + rank_code
    + region
    + market_name
    + requested_convert_kg

## 10. 구현 체크리스트

- [ ] KAMIS Open API 인증키와 요청자 ID 발급 확인
- [ ] 실제 인증값은 환경변수에만 저장
- [ ] productInfo JSON·XML 파서 테스트
- [ ] 빈 배열·빈 문자열·누락 필드 정규화
- [ ] 도매·소매 등급코드 분리 호출
- [ ] 1년 초과 요청 방지
- [ ] HTTP 상태와 KAMIS 오류 코드 동시 검사
- [ ] 001 무자료와 네트워크 실패 구분
- [ ] price 문자열 숫자 변환과 결측 처리
- [ ] 전체지역 및 지역별 응답 구조 비교
- [ ] p_convert_kg_yn=Y/N 결과 검증
- [ ] 3년 백필 구간 경계 중복 제거
- [ ] 인증정보·쿠키·실제 요청 URL 로그 마스킹

## 11. 공식 출처

- [KAMIS Open API 이용안내](https://www.kamis.or.kr/customer/reference/openapi_list.do)
- [농축수산물 품목 및 등급 코드표](https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=15)
- [기간별 품목별 도매 가격 API](https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=16)
- [기간별 품목별 소매 가격 API](https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=17)

