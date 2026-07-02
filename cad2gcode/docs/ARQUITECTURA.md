# Arquitectura — sistema agéntico CAD → código máquina

## 1. Objetivo

Convertir la información de fabricación de una pieza (modelo 3D, plano 2D acotado)
en un programa CNC listo para revisar, para cualquier máquina del taller.

- **MVP (hoy):** `.step` → G-code Fanuc para Doosan DNM 5700 (centro vertical 3 ejes),
  operaciones de taladrado.
- **Cliente piloto:** programa hoy con NX CAM (Siemens). El STEP de entrada sale de NX,
  y el plano 2D en PDF también. A futuro el sistema debe leer ese plano (cotas,
  tolerancias, acabados) porque el STEP solo lleva geometría, no intención de diseño.

## 2. Principio de diseño: modelo intermedio

La clave para "cualquier entrada → cualquier máquina" es no acoplar nunca el formato
de entrada con el dialecto de salida. Todo pasa por un **modelo intermedio de
features de fabricación** (`cad2gcode/features/model.py`):

```
PartModel
├── stock / caja envolvente (material en bruto)
├── material ("aluminio", "acero", ...)
└── features
    ├── Hole      (posición, diámetro, profundidad, pasante o ciego, ¿roscado?)
    ├── Pocket    (contorno, profundidad)          ← definido, sin detección aún
    └── Contour   (perfil exterior, profundidad)   ← definido, sin detección aún
```

Esto es deliberadamente parecido a lo que hace NX CAM internamente (feature-based
machining): el agente razona sobre *features de mecanizado*, no sobre triángulos ni
sobre líneas de G-code.

## 3. Capas

### 3.1 Readers (`cad2gcode/readers/`)

Convierten un archivo en un `PartModel`. Cada reader declara qué extensiones acepta.

- **`step_reader.py` (MVP):** parser propio de STEP Part 21 (ISO 10303-21), sin
  dependencias. Extrae `CARTESIAN_POINT`, `DIRECTION`, `AXIS2_PLACEMENT_3D`,
  `CYLINDRICAL_SURFACE` y `CIRCLE`, y con eso:
  - caja envolvente de la pieza (de la nube de puntos),
  - agujeros: superficies cilíndricas con eje paralelo a Z; el diámetro sale del
    radio, la posición del eje, y la profundidad de la extensión en Z de los
    círculos/aristas asociados al mismo eje (si no es determinable, se asume
    pasante = espesor de la pieza y se marca `verified=False` para revisión).

  *Limitación asumida:* no es un kernel B-rep. Para piezas prismáticas taladradas
  funciona; para geometría compleja el plan es migrar a OpenCascade (`pythonocc-core`
  / `build123d`) manteniendo la misma interfaz `Reader`.

- **Futuro:** `dxf_reader` (planos 2D), `pdf_reader` (plano escaneado → visión con
  Claude para extraer cotas y tolerancias — es la pieza que convierte esto en un
  sistema "que lee planos" de verdad).

### 3.2 Base de conocimiento de máquinas (`cad2gcode/knowledge/`)

Un JSON por máquina: carreras, husillo, cono, cambiador, dialecto de control y
particularidades del post. `doosan_dnm5700.json` es la referencia. Añadir una
máquina no toca código: se añade el JSON y (si el control es nuevo) un postprocesador.

### 3.3 Planner (`cad2gcode/planner/`)

Convierte `PartModel` + máquina + material en un `ProcessPlan` (lista ordenada de
operaciones con herramienta, régimen de corte y ciclo).

Dos implementaciones intercambiables:

- **`rules.py` — determinista (por defecto).** Para el MVP de taladrado:
  agrupa agujeros por diámetro, antepone centrado, elige G81 (profundidad ≤ 3×D)
  o G83 con rotura de viruta (Q = D/2) para agujero profundo, y calcula S y F a
  partir de una tabla de datos de corte por material (Vc y avance por vuelta).
  Sirve de línea base verificable y de red de seguridad sin API.

- **`agent.py` — agéntico (opcional, `--agent`).** Un agente sobre la API de Claude
  (`claude-opus-4-8`, razonamiento adaptativo) con herramientas:
  - `get_machine_spec` — consulta la ficha de la máquina,
  - `get_cutting_data` — tabla de datos de corte,
  - `submit_plan` — entrega el plan final validado contra el mismo esquema
    (`ProcessPlan`) que usa el planificador por reglas.

  El agente decide secuencia, agrupación de herramientas y regímenes justificando
  sus elecciones; el harness **valida** el plan (límites de máquina, herramientas
  coherentes, profundidades alcanzables) antes de postprocesar. Si la validación
  falla o no hay credenciales, se degrada al planificador por reglas.

  Este es el punto donde el sistema escala en inteligencia: tolerancias del plano →
  elección de escariado/mandrinado, acabados → pasadas de acabado, amarres, etc.

### 3.4 Postprocessors (`cad2gcode/postprocessors/`)

Convierten `ProcessPlan` en texto de programa para un control concreto.

- **`doosan_dnm5700.py` (MVP):** dialecto Fanuc i. Cabecera segura
  (G90 G17 G21 G40 G49 G80), G54, cambio de herramienta con G43 H, ciclos fijos
  G81/G83, retirada G91 G28, M30. Verifica que cada punto cae dentro de las
  carreras de la máquina y que S no supera el husillo.
- **Futuro:** `siemens_840d.py` (ShopMill/DIN, relevante porque el cliente usa NX y
  Siemens), `heidenhain.py`, etc.

### 3.5 CLI (`cad2gcode/cli.py`)

`convert` (pipeline completo) e `inspect` (solo lectura de features, para depurar
la interpretación del STEP antes de fiarse del código).

## 4. Flujo agéntico completo (visión)

```
plano PDF + STEP ──▶ agente lector (visión: cotas, tolerancias, material, rugosidades)
                        │
                        ▼
                 PartModel enriquecido (feature + tolerancia + acabado)
                        │
                        ▼
                 agente planificador (proceso, herramientas, amarres, fases)
                        │                      ▲
                        ▼                      │ herramientas: specs máquina,
                 validador determinista ───────┘ catálogo de herramientas del taller,
                        │                        datos de corte, histórico de piezas
                        ▼
                 postprocesador máquina destino
                        │
                        ▼
                 programa CNC + hoja de proceso + avisos para el programador
```

Reglas del sistema:

1. **El LLM nunca escribe G-code directamente.** Propone un plan estructurado; el
   G-code lo emite siempre un postprocesador determinista y verificable. Esto acota
   el riesgo: un plan malo se detecta en validación, no en la máquina.
2. **Todo plan lleva trazabilidad:** qué feature origina cada operación y por qué se
   eligió cada régimen (el agente lo justifica en el plan).
3. **Humano en el bucle:** la salida es "programa para revisar", no "programa para
   ejecutar". La simulación (NX/Vericut) sigue siendo obligatoria.

## 5. Encaje con NX Siemens (cliente piloto)

- **Corto plazo:** NX exporta STEP → este pipeline. Cero cambio de flujo para ellos;
  el sistema compite con "programar a mano una pieza sencilla".
- **Medio plazo:** leer el plano PDF que sale de NX Drafting (cotas/tolerancias) y
  el postprocesador Siemens 840D, de modo que la salida se pueda comparar 1:1 con
  lo que produce su NX CAM.
- **Largo plazo:** integración NXOpen (Python) para leer el `.prt` nativo con PMI
  (anotaciones 3D), que elimina la pérdida de información del STEP.

## 6. Roadmap técnico

1. **v0 (este repo):** taladrado STEP → DNM 5700, planner reglas + agente, tests.
2. **v0.2:** detección de cajeras/contornos (migración del reader a OpenCascade),
   fresado 2.5D, compensación de radio.
3. **v0.3:** reader de planos PDF con visión (cotas, tolerancias, roscas M en el
   plano que el STEP no lleva), catálogo de herramientas real del taller.
4. **v0.4:** post Siemens 840D, hoja de proceso, comparación contra programas NX
   reales del cliente (benchmark de aceptación).
5. **v1:** amarres y fases múltiples, simulación de trayectorias, aprendizaje del
   histórico del taller (memoria del agente).
