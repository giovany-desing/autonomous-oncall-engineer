"""
Prueba manual de concurrencia real contra DynamoDB. Lanza N hilos que
intentan registrar EXACTAMENTE el mismo fingerprint al mismo tiempo
(usando una barrera para sincronizar el arranque), y verifica que solo
UNO de ellos gane la condición atómica -- confirmando que el
ConditionExpression de DynamoDB previene duplicados incluso bajo
concurrencia real, no solo en llamadas secuenciales.
"""
import threading
import time

from dedup.fingerprint import check_and_register_fingerprint

NUM_THREADS = 10
PROJECT_NAME = "concurrency-test"
TRIGGER_SUMMARY = f"Prueba de concurrencia real {time.time()}"  # unico por corrida
REGION = "us-east-1"

results = []
results_lock = threading.Lock()
barrier = threading.Barrier(NUM_THREADS)


def worker(thread_id: int):
    barrier.wait()  # todos los hilos arrancan la llamada al mismo instante
    result = check_and_register_fingerprint(PROJECT_NAME, TRIGGER_SUMMARY, REGION)
    with results_lock:
        results.append((thread_id, result.is_duplicate))


if __name__ == "__main__":
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [tid for tid, is_dup in results if not is_dup]
    losers = [tid for tid, is_dup in results if is_dup]

    print(f"Hilos que lanzaron la llamada simultaneamente: {NUM_THREADS}")
    print(f"Hilos que ganaron (is_duplicate=False): {len(winners)} -> {winners}")
    print(f"Hilos que perdieron (is_duplicate=True): {len(losers)} -> {losers}")
    print()
    if len(winners) == 1:
        print("RESULTADO: correcto -- exactamente 1 hilo gano, sin condicion de carrera.")
    else:
        print(f"RESULTADO: PROBLEMA -- {len(winners)} hilos ganaron, deberia ser exactamente 1.")
