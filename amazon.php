<?php
// Proxy simples: busca a página do produto na Amazon e extrai os dados.
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
$url = $_GET['url'] ?? '';
if (!preg_match('#^https?://[^\s]+$#', $url)) { http_response_code(400); echo json_encode(['error'=>'url inválida']); exit; }

$ch = curl_init($url);
curl_setopt_array($ch, [
  CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => true, CURLOPT_MAXREDIRS => 10,
  CURLOPT_TIMEOUT => 30, CURLOPT_ENCODING => '',
  CURLOPT_USERAGENT => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
  CURLOPT_HTTPHEADER => ['Accept-Language: pt-BR,pt;q=0.9', 'Accept: text/html,application/xhtml+xml'],
]);
$html = curl_exec($ch);
$final = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if (!$html) { echo json_encode(['error'=>'sem resposta', 'status'=>$code]); exit; }

function grab($re, $html, $i = 1) { return preg_match($re, $html, $m) ? trim(html_entity_decode(strip_tags($m[$i]), ENT_QUOTES, 'UTF-8')) : ''; }

$asin = grab('#/dp/([A-Z0-9]{10})#', $final);
$captcha = stripos($html, 'captcha') !== false && stripos($html, 'productTitle') === false;

$out = [
  'url_final' => $final,
  'asin' => $asin,
  'titulo' => grab('#<span[^>]*id="productTitle"[^>]*>(.*?)</span>#s', $html),
  'preco' => grab('#id="corePriceDisplay_desktop_feature_div".*?<span class="a-offscreen">(.*?)</span>#s', $html)
          ?: grab('#id="corePrice_feature_div".*?<span class="a-offscreen">(.*?)</span>#s', $html)
          ?: grab('#class="a-price[^"]*".*?<span class="a-offscreen">(.*?)</span>#s', $html),
  'preco_antigo' => grab('#class="basisPrice".*?<span class="a-offscreen">(.*?)</span>#s', $html)
          ?: grab('#<span class="a-price a-text-price"[^>]*>.*?<span class="a-offscreen">(.*?)</span>#s', $html),
  'desconto' => grab('#class="[^"]*savingsPercentage[^"]*"[^>]*>\s*(-?\d+%)#s', $html),
  'avaliacao' => grab('#<span[^>]*id="acrPopover"[^>]*title="([^"]*)"#', $html),
  'num_avaliacoes' => grab('#id="acrCustomerReviewText"[^>]*>(.*?)</span>#s', $html),
  'vendas' => grab('#id="social-proofing-faceout-title-tk_bought"[^>]*>.*?<span[^>]*>(.*?)</span>#s', $html),
  'cupom' => grab('#id="couponText[^"]*"[^>]*>(.*?)</(?:span|label)>#s', $html)
          ?: grab('#<label[^>]*for="checkbox[^"]*"[^>]*>(.*?)</label>#s', $html),
  'frete' => grab('#id="mir-layout-DELIVERY_BLOCK[^"]*".*?data-csa-c-delivery-price="([^"]*)"#s', $html)
          ?: (stripos($html, 'Frete GRÁTIS') !== false ? 'Frete GRÁTIS' : ''),
  'imagem' => grab('#id="landingImage"[^>]*src="([^"]*)"#', $html),
  'captcha' => $captcha,
  'status' => $code,
];
echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
