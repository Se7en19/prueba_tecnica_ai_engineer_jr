# Servicio de recursos educativos con IA (Didacteca)

`POST /execute` recibe una acción (`chat`, `quiz` o `activity`), pide la sección del libro al Context Service y le pasa ese texto a OpenAI (`gpt-4.1-mini`) para responder una pregunta, generar un quiz o diseñar una actividad. El modelo solo puede usar el contenido de la sección.

Implementé las tres capacidades, conectadas al Context Service y a OpenAI reales. Tiempo aproximado dedicado: 4 h.

## Instalación

Necesitas Python 3.12 o más reciente.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración

Copia el archivo de ejemplo y pon tu clave en `.env`:

```bash
cp .env.example .env
```

| Variable | Para qué sirve |
|---|---|
| `OPENAI_API_KEY` | Clave de OpenAI que entrega Didacteca. Vive solo en `.env`, que Git ignora. |
| `OPENAI_MODEL` | Modelo a usar. Si no la defines, se usa `gpt-4.1-mini`. |
| `PROVIDED_SERVICE_BASE_URL` | URL base del Context Service. Si no la defines, se usa `https://temp.didacteca.site`. |

## Ejecución

```bash
uvicorn src.main:app --reload
```

La documentación interactiva queda en http://127.0.0.1:8000/docs.

## Ejemplos

### Chat

```bash
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"chat","book_id":"book_001","section_id":"section_04","instructions":"¿Qué es el discriminante?"}'
```

```json
{"action": "chat", "answer": "El discriminante es Δ = b² − 4ac ...", "warnings": []}
```

### Quiz

```bash
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"quiz","book_id":"book_002","section_id":"section_01","instructions":"Genera un quiz de 3 preguntas."}'
```

### Activity

```bash
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"activity","book_id":"book_001","section_id":"section_05","instructions":"Crea una actividad para realizar en equipos."}'
```

### Casos problemáticos

```bash
# Pregunta fuera del contenido -> 422 NOT_IN_CONTENT
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"chat","book_id":"book_001","section_id":"section_04","instructions":"¿Quién ganó el mundial 2010?"}'

# Instrucciones contradictorias -> 422 NEEDS_CLARIFICATION
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"quiz","book_id":"book_001","section_id":"section_04","instructions":"Quiz de 3 preguntas muy fáciles y a la vez de nivel experto, sin preguntas."}'

# Sección inexistente -> 404 SECTION_NOT_FOUND
curl -X POST http://127.0.0.1:8000/execute -H "Content-Type: application/json" \
  -d '{"action":"chat","book_id":"book_001","section_id":"section_inexistente","instructions":"hola"}'
```

## Formato de respuestas

Una respuesta exitosa (HTTP 200) tiene el esquema que define la prueba para cada acción, más un campo `warnings`. Ahí van los valores por defecto que se aplicaron o la parte de la solicitud que no se pudo cumplir. Si `warnings` viene vacía, el resultado está completo.

Los errores y las solicitudes de aclaración usan siempre la misma forma. El cliente decide con `code`; `message` es para mostrárselo a una persona.

```json
{"status": "error", "code": "NEEDS_CLARIFICATION", "message": "Qué pasó y qué debe aclarar el usuario"}
```

| HTTP | `code` | Cuándo ocurre |
|---|---|---|
| 422 | `INVALID_REQUEST` | Falta un campo, viene vacío o `action` no es chat, quiz ni activity. Trae `fields` con los campos a corregir. |
| 404 | `BOOK_NOT_FOUND` / `SECTION_NOT_FOUND` | El Context Service no encuentra el libro o la sección. |
| 422 | `EMPTY_CONTENT` | La sección existe pero no tiene contenido. |
| 422 | `NOT_IN_CONTENT` | Con el contenido no se puede responder ni generar el recurso. |
| 422 | `NEEDS_CLARIFICATION` | Las instrucciones son ambiguas o se contradicen. `message` dice qué aclarar. |
| 504 | `CONTEXT_UNAVAILABLE` / `CONTEXT_ERROR` | El Context Service no responde, tarda demasiado o contesta algo inesperado. |
| 504 | `IA_UNAVAILABLE` | Falla la llamada a OpenAI (red, cuota o credencial). |
| 504 | `INVALID_AI_RESPONSE` | La IA devolvió algo que no cumple el esquema. No se presenta como éxito. |

Todos los fallos de servicios externos devuelven 504. Lo decidí así para que el cliente tenga un solo código que signifique "falló algo que no depende de tu solicitud".

## Pruebas

```bash
python -m pytest -q
```

Las pruebas reemplazan con mocks `httpx.post` (Context Service) y `call_llm` (OpenAI), así que no gastan la clave. Revisan la validación de entrada, el 404 y el contenido vacío del Context Service, el timeout, los casos de éxito de chat y quiz, la pregunta fuera del contenido y la petición de aclaración. También cubren tres formas de salida inválida de la IA: texto que no es JSON, un `correct_answer` que no está entre las `options` y un `status: ok` sin resultado. Otra prueba comprueba que el contenido del libro viaja delimitado en el mensaje de usuario y nunca en el prompt de sistema.

## Arquitectura

Todo vive en `src/main.py`, unas 150 líneas:

```
Req (Pydantic) -> get_context (httpx) -> generate(action) -> call_llm (OpenAI) -> Envelope -> esquema de la acción -> respuesta
```

`Req` valida la entrada antes de llamar a ningún servicio. `get_context` llama al Context Service y traduce sus errores a nuestro formato. `SPECS` asocia cada acción con su prompt y su esquema Pydantic de éxito, así que agregar una acción es agregar una entrada ahí. `generate` es el flujo común: arma el mensaje, llama una vez al modelo y valida primero el sobre y después el resultado. `call_llm` es el único lugar que habla con OpenAI, y por eso es también donde las pruebas ponen el mock. `ApiError` y su handler dan el formato único de error.

## Decisiones técnicas

- Hago una sola llamada al modelo por solicitud. El mismo modelo genera el recurso y dice si pudo hacerlo (`status`). Un paso previo de clasificación duplicaría las llamadas y no lo necesité.
- El modelo siempre responde con un sobre `{status, message, warnings, result}`. Solo si `status` es `ok` valido `result` contra el esquema de la acción. Así el éxito, el rechazo y la aclaración llegan estructurados.
- Pydantic revisa la forma de la salida y una regla de contenido: `correct_answer` tiene que ser una de las `options`.
- Uso el modo JSON de OpenAI (`response_format: json_object`), pero no confío solo en él y valido todo igual.
- El contenido del libro es material de referencia, no instrucciones. Va en el mensaje de usuario dentro de `<contenido>`, separado de `<instrucciones>`, y el prompt de sistema le pide al modelo ignorar cualquier orden escrita dentro del contenido.
- Si falta un dato, aplico un valor por defecto y lo aviso en `warnings` (5 preguntas en el quiz, 20 minutos en la actividad). Si las instrucciones se contradicen, no genero nada y respondo `NEEDS_CLARIFICATION`.
- No usé LangChain ni otro framework. Con una llamada por solicitud, el SDK de OpenAI alcanza.

## Supuestos

- Las preguntas del quiz son de opción múltiple con 4 opciones.
- El modelo responde en el idioma del contenido, que en los ejemplos es español.
- No guardo estado. Para aclarar algo, el cliente manda una solicitud nueva y completa.
- Agregar `warnings` a las respuestas de éxito no rompe el esquema de la prueba, porque solo añade un campo.

## Limitaciones conocidas

- El propio modelo decide si algo está en el contenido, y se puede equivocar en las dos direcciones: decir `ok` después de rellenar con lo que ya sabía, o rechazar algo que sí estaba.
- Valido la estructura, no la verdad. Nada comprueba que la `correct_answer` sea de verdad la correcta ni que cada afirmación salga de la sección.
- Los delimitadores y las reglas contra prompt injection bajan el riesgo, pero un texto bien armado todavía podría colarse.
- Si la IA devuelve algo inválido no reintento. El SDK de OpenAI sí reintenta por su cuenta los errores de red y los 5xx.
- No recorto el contenido. Una sección muy larga podría pasarse del contexto del modelo.

## Documento de decisiones

### 1. ¿Cómo dividiste el problema?

Vi cinco responsabilidades: validar la entrada, traer el contenido y traducir los errores del Context Service, armar el prompt con las reglas, el contenido y las instrucciones separados, llamar al modelo y validar su salida antes de devolverla. Empecé con una sola capacidad completa de punta a punta (chat). Cuando funcionó, generalicé el flujo para quiz y activity.

### 2. ¿Por qué elegiste esta arquitectura?

Las tres acciones hacen lo mismo y solo cambian el prompt y el esquema de salida. Con un diccionario (`SPECS`) y una función (`generate`) no repito código, y no necesito clases ni capas que un problema de este tamaño no pide. Dejé todo en un archivo porque se puede leer completo de una sentada.

### 3. ¿Qué situaciones consideraste problemáticas?

Hubo varios casos en los que decidí no generar nada, o no generarlo todo:

- Si falta un campo o viene vacío, rechazo la solicitud antes de llamar a cualquier servicio y digo cuáles faltan. Nunca invento un id.
- Si el libro o la sección no existen, devuelvo el 404 con el código que manda el Context Service.
- Una sección vacía (200 con `content` vacío) es un problema del contenido, no de la red, así que tiene su propio código: `EMPTY_CONTENT`.
- Si la pregunta o el tema no está en la sección, respondo `NOT_IN_CONTENT` en lugar de dejar que el modelo use lo que sabe.
- Si las instrucciones se contradicen, respondo `NEEDS_CLARIFICATION` y digo qué hay que aclarar.
- Si las instrucciones están incompletas, genero con valores por defecto y los informo en `warnings`.
- Si el contenido o las instrucciones intentan cambiar la tarea (prompt injection), el prompt de sistema le dice al modelo que no obedezca.
- Si el modelo devuelve una salida inválida, nunca la presento como éxito.

### 4. ¿Qué limitaciones tiene tu solución?

Están en "Limitaciones conocidas". La más seria es que la fidelidad al contenido depende del modelo, y yo solo valido la estructura de lo que devuelve.

### 5. ¿Qué mejorarías si tuvieras más tiempo?

- Reintentaría una vez cuando la salida es inválida, pasándole al modelo el error de validación.
- Usaría salidas estructuradas con JSON Schema estricto (`response_format: json_schema`), generado desde los modelos Pydantic.
- Verificaría la fundamentación con una segunda llamada o con reglas que revisen que cada respuesta y cada explicación tengan respaldo en el contenido.
- Agregaría logs estructurados, métricas de latencia y costo por acción, y un cliente HTTP asíncrono.
- Partiría `src/main.py` en módulos (prompts, esquemas, clientes) cuando crezca.

### 6. ¿Cómo evaluarías si el sistema funciona correctamente?

Las pruebas de `tests/` cubren el contrato: errores, formatos y validación. Para la calidad de las respuestas armaría un conjunto de evaluación con casos reales por sección: preguntas que sí se pueden responder y otras que no, instrucciones contradictorias o incompletas, e intentos de inyección. Cada caso llevaría su resultado esperado (`ok`, `NOT_IN_CONTENT` o `NEEDS_CLARIFICATION`).

Sobre ese conjunto mediría:

- qué porcentaje de salidas cumple el esquema;
- precisión y exhaustividad de los rechazos `NOT_IN_CONTENT`;
- qué porcentaje de afirmaciones tiene respaldo en el contenido, revisado por personas o por un modelo juez;
- si la `correct_answer` de cada pregunta es de verdad la correcta;
- latencia y costo por solicitud.

Además le pediría a un docente revisar una muestra de quizzes y actividades, porque un recurso puede ser fiel al texto y aun así no servir en clase.