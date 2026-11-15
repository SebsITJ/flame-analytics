# Formato de `experiments.csv`

El archivo actual tiene 5 filas de prueba marcadas como **SIMULATED**. No son mediciones de la NASA. Para usar los datos reales, reemplaza el archivo por uno con las mismas columnas (o apunta la variable `FLAME_DATA_PATH` a otro archivo). El código no cambia.

| Columna | Contenido | Ejemplo |
| --- | --- | --- |
| `experimento` | Nombre e identificador de la prueba | `FLEX Test 2-15` |
| `combustible` | Combustible o material | `n-heptane` |
| `oxigeno` | O2 en % por volumen (`21` o `21 %`) | `21` |
| `presion` | Presión en **atm** | `1.0` |
| `resultado` | Qué pasó, en texto o número | `Radiative extinction at 4.1 mm` |
| `fase` | `prevent`, `detect` o `extinguish` | `extinguish` |
| `fuente` | DOI o enlace de NASA PSI | `10.60555/xxxx-xxxx` |

Notas:

- Encabezados en inglés también sirven (`experiment, fuel, oxygen, pressure, result, phase, source`), con o sin tildes.
- Separador: coma, punto y coma, tabulación o `|`. Codificación: UTF-8 o cp1252 (Excel en español). Se detecta sola.
- Decimales con coma (`0,7`) se leen bien. El oxígeno va en porcentaje: escribe `21`, no `0,21`.
- Los valores originales no se modifican. La app agrega columnas numéricas aparte y lista en la barra lateral las filas con problemas (número ilegible, fase no válida, sin fuente).
- Cualquier fila que contenga la palabra `SIMULATED` activa un aviso permanente en la app.
