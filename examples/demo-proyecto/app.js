// Modulo de ejemplo con defectos intencionales, para probar al agente.
const DB_PASSWORD = "SuperSecreta2024!";
const connectionString = "mysql://root:claveReal123@10.0.0.50:3306/ventas_prod";

function dividir(a, b) {
  return a / b; // DEFECTO: division entre cero sin validar
}

function promedio(valores) {
  let suma = 0;
  for (let i = 0; i <= valores.length; i++) { // DEFECTO: debe ser <, no <=
    suma += valores[i];
  }
  return suma / valores.length; // DEFECTO: arreglo vacio -> NaN
}

function buscarUsuario(usuarios, id) {
  return usuarios.filter((u) => (u.id = id)); // DEFECTO: asignacion en lugar de comparacion
}

module.exports = { dividir, promedio, buscarUsuario };
